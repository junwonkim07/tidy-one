"""Two encoders of one vector space working a shared, length-sorted queue: on Apple Silicon the GPU
(torch MPS) and the Neural Engine (Core ML) embed passages at the same time.

The GPU takes token-budget batches from the long end of the queue; the Neural Engine takes single texts
from the short end, where its fixed-length programs are cheapest. The Neural Engine joins only once a
process has a real backlog (`assist_after` passages), so small incremental runs never pay for a Core ML
load. Its programs then load in one background thread, longest bucket first (it holds every text), and
nothing waits on them: until a program is ready the GPU does all the work.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections import deque

import numpy as np

from tidy_one.embed.coreml_text import CoreMLTextEncoder
from tidy_one.embed.text import BaseEncoder, pad_batch

log = logging.getLogger("tidy_one.embed")

ASSIST_AFTER = 512  # passages this process embeds on the GPU alone before the Neural Engine joins
POLL_S = 0.2
QOS_CLASS_UTILITY = 0x11


def yield_to_foreground() -> None:
    """Lower the calling thread to utility QoS on macOS, so a Core ML load leaves the GPU feeder its cores."""
    if sys.platform != "darwin":
        return
    try:
        ctypes.CDLL("/usr/lib/libSystem.dylib").pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0)
    except (OSError, AttributeError):
        pass


class TandemEncoder:
    """`primary` (GPU, batches) plus an optional `helper` (Neural Engine, one text at a time)."""

    def __init__(self, primary: BaseEncoder, helper: CoreMLTextEncoder | None, assist_after: int = ASSIST_AFTER):
        self.primary = primary
        self.helper = helper
        self.assist_after = assist_after
        self.model_id = primary.model_id
        self.dim = primary.dim
        self.encoded = 0
        self.helped = 0  # passages the helper embedded
        self._loader: threading.Thread | None = None
        self._loader_lock = threading.Lock()
        self._helper_failed = helper is None

    @property
    def available(self) -> bool:
        return self.primary.available

    @property
    def max_len(self) -> int:
        return self.primary.max_len

    def count_tokens(self, texts: list[str]) -> list[int]:
        return self.primary.count_tokens(texts)

    def encode_query(self, text: str) -> np.ndarray:
        return self.primary.encode_query(text)

    def preload(self) -> None:
        """Load every helper program now and wait for them (benchmarks, known-long runs)."""
        if self.helper is not None:
            self._start_loading().join()

    def _start_loading(self) -> threading.Thread:
        with self._loader_lock:
            if self._loader is None:
                self._loader = threading.Thread(target=self._load_all, name="tidy-coreml-load", daemon=True)
                self._loader.start()
            return self._loader

    def _load_all(self) -> None:
        h = self.helper
        assert h is not None
        yield_to_foreground()
        try:
            for b in (h.buckets[-1], *h.buckets[:-1]):
                h.preload([b])
        except Exception as e:
            self._helper_failed = True
            log.warning("Neural Engine encoder unavailable (%s: %s); using the GPU only", type(e).__name__, e)

    def encode_passages(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        """(n, dim) float32, unit norm, in input order."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        p = self.primary
        p._ensure()
        ids = p._ids(texts)
        queue = deque(sorted(range(len(ids)), key=lambda i: len(ids[i])))
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        done = np.zeros(len(texts), dtype=bool)
        lock = threading.Lock()
        stop = threading.Event()
        working = threading.Event()

        def take_long() -> list[int]:
            with lock:
                if not queue:
                    return []
                width = max(len(ids[queue[-1]]), 1)
                cap = max(batch_size, p.max_tokens // width) if p.max_tokens else batch_size
                if working.is_set():  # leave the helper its share of the tail so both finish together
                    cap = min(cap, max(1, len(queue) // 2))
                return [queue.pop() for _ in range(min(cap, len(queue)))]

        def run_primary() -> None:
            while batch := take_long():
                out[batch] = p._finish(p._embed(*pad_batch([ids[i] for i in batch], p._pad_id)))
                done[batch] = True

        helper = None
        if not self._helper_failed and self.encoded + len(texts) > self.assist_after:
            helper = threading.Thread(
                target=self._assist, args=(ids, queue, lock, out, done, stop, working), daemon=True
            )
            helper.start()
        try:
            run_primary()
        finally:
            stop.set()
            if helper is not None:
                helper.join()
        try:
            run_primary()  # anything the helper handed back
        finally:
            p._done()
        assert done.all()
        self.encoded += len(texts)
        return out

    def _assist(
        self, ids: list[list[int]], queue: deque[int], lock: threading.Lock, out: np.ndarray, done: np.ndarray,
        stop: threading.Event, working: threading.Event,
    ) -> None:
        h = self.helper
        assert h is not None
        loader = self._start_loading()
        try:
            while not stop.is_set() and not self._helper_failed:
                with lock:
                    if not queue:
                        return
                    bucket = h.ready_bucket(len(ids[queue[0]]))
                    i = queue.popleft() if bucket is not None else None
                if i is None:
                    working.clear()
                    loader.join(POLL_S)
                    continue
                working.set()
                try:
                    out[i] = h.embed_one(ids[i], bucket)
                except Exception as e:
                    with lock:
                        queue.appendleft(i)
                    self._helper_failed = True
                    log.warning("Neural Engine encoder failed (%s: %s); using the GPU only", type(e).__name__, e)
                    return
                done[i] = True
                self.helped += 1
        finally:
            working.clear()
