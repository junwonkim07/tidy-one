/* tidy-one site: language memory, menu, hero pixel field, footer game. No dependencies. */
(function () {
  "use strict";

  var doc = document;
  var root = doc.documentElement;
  var page = root.getAttribute("data-page") || "ko";
  var STORE = "tidy-one:lang";
  var reduceMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) {
      return null;
    }
    return null;
  }

  /* ---------------------------------------------------------- language */
  function initLanguage() {
    // Section ids are the same on every page, so the switcher keeps the reader's place.
    var links = doc.querySelectorAll("[data-lang]");
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener("click", function () {
        store(STORE, this.getAttribute("data-lang"));
        var base = (this.getAttribute("href") || "").split("#")[0];
        if (window.location.hash) this.setAttribute("href", base + window.location.hash);
      });
    }

    // First visit to the Korean root: suggest (never force) another language.
    if (page !== "ko" || store(STORE)) return;
    var bar = doc.getElementById("lang-suggest");
    var dataEl = doc.getElementById("lang-data");
    if (!bar || !dataEl) return;
    var data;
    try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }

    var prefs = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ""]);
    var first = String(prefs[0] || "").toLowerCase();
    if (!first || first.indexOf("ko") === 0) return;
    var want = first.indexOf("zh") === 0 ? "zh" : "en";
    var t = data[want];
    var ko = data.ko;
    if (!t || !ko) return;

    var label = doc.createElement("span");
    label.className = "label";
    label.lang = t.lang;
    label.textContent = t.label;

    var go = doc.createElement("a");
    go.href = t.href + window.location.hash;
    go.lang = t.lang;
    go.hreflang = t.lang;
    go.textContent = t.name + " →";
    go.addEventListener("click", function () { store(STORE, want); });

    var stay = doc.createElement("button");
    stay.type = "button";
    stay.lang = ko.lang;
    stay.textContent = ko.name;
    stay.addEventListener("click", function () {
      store(STORE, "ko");
      bar.hidden = true;
      // keep keyboard users near where they were: the current language in the visible switcher
      var cur = doc.querySelectorAll('.lang-switch a[aria-current="page"]');
      for (var k = 0; k < cur.length; k++) {
        if (cur[k].offsetParent !== null) { cur[k].focus(); return; }
      }
      var brand = doc.querySelector(".brand");
      if (brand) brand.focus();
    });

    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", t.label);
    bar.lang = t.lang; // the region is named in the suggested language, so say which
    bar.appendChild(label);
    bar.appendChild(go);
    bar.appendChild(stay);
    bar.hidden = false;
  }

  /* ---------------------------------------------------------- menu */
  function initMenu() {
    var btn = doc.querySelector(".menu-btn");
    var menu = doc.getElementById("site-menu");
    if (!btn || !menu) return;
    function set(open) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      menu.classList.toggle("is-open", open);
    }
    btn.addEventListener("click", function () {
      set(btn.getAttribute("aria-expanded") !== "true");
    });
    menu.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("a")) set(false);
    });
    doc.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && btn.getAttribute("aria-expanded") === "true") {
        set(false);
        btn.focus();
      }
    });
  }

  /* ---------------------------------------------------------- hero pixel field
     Scattered: pixels hang from the hairline in loose clouds with ragged, dissolving edges,
     slightly off the grid and slightly smaller. Scrolling tidies them in a wave from left to
     right: each pixel travels to its own cell and clicks into place, filling 3 x 3 tiles (the
     mark's pattern) sorted from slate to mist. The tiles fill the whole field, centred with an
     even margin, so the tidy end state has no empty band. The loop runs only while something
     moves: while the field catches up with the scroll, plus a slow, short drift (~10 fps,
     under 5 s) after load or a scroll, then it sleeps. */
  function initField() {
    var canvas = doc.getElementById("tidy-grid");
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var hero = canvas.closest(".hero") || root;

    var TONES = ["#2F3E46", "#354F52", "#52796F", "#84A98C", "#CAD2C5"];
    var TONE_STEPS = [0.22, 0.42, 0.62, 0.82];
    var DUR = 0.32;       // share of the scroll range one pixel spends travelling
    var WAVE = 0.62;      // pixels set off in a wave from left to right over this share
    var SNAP = 0.9;       // point of the trip where a pixel clicks into its cell
    var DRIFT_MS = 4800;  // idle drift after load or the last scroll (under 5 s, WCAG 2.2.2)
    var FADE_MS = 1500;   // the drift eases out over this long before the loop sleeps

    var W = 0, H = 0, dpr = 1, cell = 12, gap = 2, cols = 0, rows = 0, ox = 0;
    var px = [], bg = null;
    var P = 0, target = 0, visible = true, raf = 0, timer = 0, last = 0, idleUntil = 0, tidyOut = "";

    var seed = 1;
    function rand() {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    }
    function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
    function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
    function smooth(a, b, x) { var t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
    function toneAt(t) {
      var c = 0;
      while (c < TONE_STEPS.length && t > TONE_STEPS[c]) c++;
      return c;
    }

    function build() {
      var r = canvas.getBoundingClientRect();
      W = Math.max(1, r.width);
      H = Math.max(1, r.height);
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      cell = W < 640 ? 9 : W < 1100 ? 11 : 13;
      gap = W < 640 ? 1.5 : 2;
      // whole cells only, centred across the width: no half-cut squares at the edges. An odd
      // count both ways, so the tile block (4n - 1 cells) sits exactly in the middle.
      cols = Math.floor((W + gap) / cell);
      rows = Math.floor((H + gap) / cell);
      if (cols % 2 === 0) cols--;
      if (rows % 2 === 0) rows--;
      ox = Math.round((W - (cols * cell - gap)) / 2);
      seed = 20261010;

      // 1. tidy end state: 3 x 3 tiles with one-cell gutters filling the field, with the same
      //    one- or two-cell margin on opposite sides
      var ntx = Math.max(1, Math.floor((cols - 1) / 4));
      var nty = Math.max(1, Math.floor((rows - 1) / 4));
      var tx0 = (cols - (ntx * 4 - 1)) / 2;
      var ty0 = (rows - (nty * 4 - 1)) / 2;
      var homes = [];
      for (var ty = 0; ty < nty; ty++) {
        for (var tx = 0; tx < ntx; tx++) {
          var c = toneAt(0.8 * (tx + 0.5) / ntx + 0.2 * (ty + 0.5) / nty);
          for (var k = 0; k < 9; k++) {
            var hx = tx0 + tx * 4 + (k % 3), hy = ty0 + ty * 4 + ((k / 3) | 0);
            homes.push({ hx: hx, hy: hy, c: c, key: hx + (rand() - 0.5) * 6 });
          }
        }
      }
      var n = homes.length;

      // 2. scattered start: clouds hanging from the top edge with a ragged lower edge,
      //    open pockets inside and a thin trail of pixels dissolving below. The clouds hang
      //    lower until they hold about 1.6 candidate cells per pixel, so picking the strongest
      //    cells still leaves pockets and a ragged edge.
      var spots = [], base = 0.47;
      for (var tries = 0; tries < 12; tries++) {
        spots = [];
        for (var y = 0; y < rows; y++) {
          for (var x = 0; x < cols; x++) {
            var u = (x + 0.5) / cols, v = (y + 0.5) / rows;
            var edge = base + 0.2 * Math.sin(6.283 * (u * 1.1 + 0.08)) +
              0.11 * Math.sin(6.283 * (u * 2.7 + 0.55)) + 0.05 * Math.sin(6.283 * (u * 6.3 + 0.3));
            var inside = smooth(edge + 0.04, edge - 0.24, v);
            var holes = 0.5 + 0.5 * Math.sin(u * 19 + 2 * Math.sin(v * 5)) * Math.sin(v * 13 + 3 * u);
            var dens = inside * (0.5 + 0.5 * Math.pow(holes, 1.6));
            if (v > edge) dens += 0.22 * Math.exp(-(v - edge) / 0.09) * (0.5 + 0.5 * Math.sin(u * 41 + 1.7));
            var score = dens * dens * (0.45 + 0.55 * rand());
            if (score > 0.002) spots.push({ x: x, y: y, dens: dens, score: score });
          }
        }
        if (spots.length >= n * 1.4 || base >= 0.9) break;
        base += 0.04;
      }
      spots.sort(function (a, b) { return b.score - a.score; });
      spots.length = Math.min(spots.length, n);
      for (var s = 0; s < spots.length; s++) spots[s].key = spots[s].x + (rand() - 0.5) * 6;
      // pair by position across the width, so each pixel mostly moves up and in
      homes.sort(function (a, b) { return a.key - b.key; });
      spots.sort(function (a, b) { return a.key - b.key; });

      px = [];
      for (var i = 0; i < n; i++) {
        var h = homes[i], sp = spots[Math.min(i, spots.length - 1)] || { x: h.hx, y: h.hy, dens: 1 };
        var d = clamp(sp.dens, 0, 1);
        px.push({
          hx: h.hx, hy: h.hy, c: h.c,
          sx: sp.x + (rand() - 0.5) * 0.6,            // off the grid by a fraction of a cell
          sy: sp.y + (rand() - 0.5) * 0.6,
          sz: 0.6 + 0.3 * d + 0.08 * rand(),           // a little smaller while scattered
          a: 0.45 + 0.55 * Math.min(1, d * 1.6),       // faint at the dissolving edges
          // tidying sweeps across: the block fills from the left while the right still drifts
          d: WAVE * (0.82 * h.hx / Math.max(1, cols) + 0.18 * rand()),
          ph: rand() * 6.283, sp: 0.7 + rand() * 0.6
        });
      }
      px.sort(function (a, b) { return a.c - b.c; });

      // faint empty grid, drawn once
      bg = doc.createElement("canvas");
      bg.width = canvas.width;
      bg.height = canvas.height;
      var g = bg.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.fillStyle = "rgba(202, 210, 197, 0.32)";
      for (var yy = 0; yy < rows; yy++) {
        for (var xx = 0; xx < cols; xx++) g.fillRect(ox + xx * cell, yy * cell, cell - gap, cell - gap);
      }
    }

    function draw(now, live) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (bg) ctx.drawImage(bg, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var still = reduceMotion.matches;
      var s = cell - gap;
      var amp = still ? 0 : 0.22 * live;
      var lastColor = -1, lastAlpha = -1;
      for (var i = 0; i < px.length; i++) {
        var p = px[i];
        var lp = still ? 1 : clamp((P - p.d) / DUR, 0, 1);
        var X, Y, size, a = 1;
        if (lp >= SNAP) {
          X = ox + p.hx * cell;
          Y = p.hy * cell;
          size = s;
        } else {
          var e = ease(lp / SNAP);
          var x = p.sx + (p.hx - p.sx) * e;
          var y = p.sy + (p.hy - p.sy) * e;
          if (amp > 0) {
            var j = amp * (1 - e);
            x += Math.sin(now * 0.0011 * p.sp + p.ph) * j;
            y += Math.cos(now * 0.0009 * p.sp + p.ph * 1.3) * j;
          }
          size = s * (p.sz + (0.84 - p.sz) * e);
          // sub-cell positions, rounded to device pixels so edges stay crisp
          X = Math.round((ox + x * cell + (s - size) / 2) * dpr) / dpr;
          Y = Math.round((y * cell + (s - size) / 2) * dpr) / dpr;
          size = Math.round(size * dpr) / dpr;
          a = p.a + (1 - p.a) * e;
        }
        if (X >= W || Y >= H || X + size <= 0 || Y + size <= 0) continue;
        a = Math.round(a * 10) / 10;
        if (a !== lastAlpha) { ctx.globalAlpha = a; lastAlpha = a; }
        if (p.c !== lastColor) { ctx.fillStyle = TONES[p.c]; lastColor = p.c; }
        ctx.fillRect(X, Y, size, size);
      }
      ctx.globalAlpha = 1;
    }

    function setTidy() {
      var v = P.toFixed(2);
      if (v !== tidyOut) { tidyOut = v; hero.style.setProperty("--tidy", v); }
    }

    function measure() {
      var r = canvas.getBoundingClientRect();
      var scrollY = window.pageYOffset || root.scrollTop || 0;
      var top = r.top + scrollY;
      var vh = window.innerHeight || 800;
      var end = Math.max(160, top + r.height * 0.3 - vh * 0.2);
      target = clamp(scrollY / end, 0, 1);
    }

    function stop() {
      if (raf) { window.cancelAnimationFrame(raf); raf = 0; }
      if (timer) { window.clearTimeout(timer); timer = 0; }
    }

    function frame(now) {
      raf = 0;
      var dt = last ? Math.min(64, now - last) : 16;
      last = now;
      if (P !== target) {
        P += (target - P) * (1 - Math.exp(-dt / 240));
        if (Math.abs(target - P) < 0.0008) P = target;
      }
      var live = P < 0.999 ? clamp((idleUntil - now) / FADE_MS, 0, 1) : 0;
      draw(now, live);
      setTidy();
      if (!visible) return;
      if (P !== target) {
        raf = window.requestAnimationFrame(frame);            // catching up with the scroll
      } else if (live > 0) {
        timer = window.setTimeout(function () {               // slow drift, ~10 fps
          timer = 0;
          raf = window.requestAnimationFrame(frame);
        }, 90);
      }
      // otherwise everything is still: the loop sleeps until the next scroll
    }

    function kick() {
      if (reduceMotion.matches || !visible) return;
      if (timer) { window.clearTimeout(timer); timer = 0; }
      if (!raf) {
        last = 0;
        raf = window.requestAnimationFrame(frame);
      }
    }

    function drawStill() {
      P = target = 1;
      setTidy();
      draw(0, 0);
    }

    build();
    if (reduceMotion.matches) {
      drawStill();
    } else {
      measure();
      P = target; // a reload mid-page starts where the reader is
      idleUntil = performance.now() + DRIFT_MS;
      setTidy();
      draw(performance.now(), 1);
      kick();
    }

    window.addEventListener("scroll", function () {
      if (reduceMotion.matches) return; // already drawn tidy; nothing changes on scroll
      measure();
      idleUntil = performance.now() + DRIFT_MS;
      kick();
    }, { passive: true });

    var resizeTimer = 0;
    function onResize() {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(function () {
        var r = canvas.getBoundingClientRect();
        if (Math.abs(r.width - W) < 0.5 && Math.abs(r.height - H) < 0.5) return;
        build();
        if (reduceMotion.matches) { drawStill(); return; }
        measure();
        draw(performance.now(), 0);
        kick();
      }, 120);
    }
    if ("ResizeObserver" in window) new ResizeObserver(onResize).observe(canvas);
    else window.addEventListener("resize", onResize);

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        if (visible) kick();
        else stop();
      }).observe(canvas);
    }

    var onMotion = function () {
      stop();
      if (reduceMotion.matches) { drawStill(); return; }
      measure();
      P = target;
      idleUntil = performance.now() + DRIFT_MS;
      draw(performance.now(), 1);
      kick();
    };
    if (reduceMotion.addEventListener) reduceMotion.addEventListener("change", onMotion);
  }

  /* ---------------------------------------------------------- footer game */
  function initGame() {
    var game = doc.getElementById("game");
    var field = doc.getElementById("game-field");
    var slotsEl = doc.getElementById("game-slots");
    if (!game || !field || !slotsEl) return;
    var slots = slotsEl.querySelectorAll(".slot");
    var stage = game.querySelector(".game-stage");
    var board = game.querySelector(".game-board");
    var scoreEl = doc.getElementById("game-score");
    var doneEl = doc.getElementById("game-done");
    var liveEl = doc.getElementById("game-live");
    var resetBtn = doc.getElementById("game-reset");
    var pieceName = game.getAttribute("data-piece") || "{n}";
    var doneText = game.getAttribute("data-done") || "";
    var total = slots.length;
    var score = 0;
    var buttons = [];
    var doneTimer = 0;

    function pad(n) { return (n < 10 ? "0" : "") + n; }
    function animates() { return !reduceMotion.matches && !!board.animate; }

    // FLIP: measure, change the layout, then animate every element from where it was
    function flip(els, mutate) {
      var first = els.map(function (el) { return el.getBoundingClientRect(); });
      mutate();
      if (!animates()) return;
      els.forEach(function (el, k) {
        var r = el.getBoundingClientRect();
        var dx = first[k].left - r.left, dy = first[k].top - r.top;
        if (!dx && !dy) return;
        el.animate(
          [{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "translate(0,0)" }],
          { duration: 560, easing: "cubic-bezier(.25,.8,.25,1)" }
        );
      });
    }

    function spots(n) {
      // spread n points over the field without overlaps
      var out = [];
      var fw = field.clientWidth, fh = field.clientHeight;
      var size = 34, tries = 0;
      while (out.length < n && tries < 2000) {
        tries++;
        var x = Math.random() * Math.max(1, fw - size);
        var y = Math.random() * Math.max(1, fh - size);
        var ok = true;
        for (var k = 0; k < out.length; k++) {
          if (Math.abs(out[k][0] - x) < size + 10 && Math.abs(out[k][1] - y) < size + 10) { ok = false; break; }
        }
        if (ok) out.push([x, y]);
      }
      while (out.length < n) out.push([Math.random() * (fw - size), Math.random() * (fh - size)]);
      return out.map(function (p) { return [p[0] / fw * 100, p[1] / fh * 100, p[0], p[1]]; });
    }

    function setDone(done) {
      if (done === game.classList.contains("is-done")) return;
      if (done) {
        // keep the stage's height so nothing below moves, then let the board glide to the middle
        stage.style.minHeight = stage.offsetHeight + "px";
        flip([board], function () {
          game.classList.add("is-done");
          doneEl.hidden = false;
        });
        liveEl.textContent = doneText;
      } else {
        game.classList.remove("is-done");
        doneEl.hidden = true;
        stage.style.minHeight = "";
        liveEl.textContent = "";
      }
    }

    function render(focusReset) {
      scoreEl.textContent = pad(score);
      if (score !== total) return;
      window.clearTimeout(doneTimer);
      // let the last pixel land before the board moves; the reset button exists only then
      doneTimer = window.setTimeout(function () {
        setDone(true);
        // unless the reader has moved on meanwhile, focus goes from the game to the reset button
        var at = doc.activeElement;
        if (focusReset && (at === game || at === doc.body || !at)) resetBtn.focus({ preventScroll: true });
      }, animates() ? 480 : 0);
    }

    function place(btn) {
      if (btn.classList.contains("is-placed")) return;
      var hadFocus = doc.activeElement === btn;
      var i = +btn.getAttribute("data-i");
      flip([btn], function () {
        btn.classList.add("is-placed");
        btn.style.left = btn.style.top = "";
        slots[i].appendChild(btn);
      });
      var next = null;
      for (var k = 0; k < buttons.length; k++) if (!buttons[k].disabled && buttons[k] !== btn) { next = buttons[k]; break; }
      // the last piece: the game itself holds focus until the reset button appears, so focus
      // never falls back to the page (screen readers would jump to the top)
      if (hadFocus) (next || game).focus({ preventScroll: true });
      btn.disabled = true;
      score++;
      render(hadFocus && !next);
    }

    function scatter(initial) {
      window.clearTimeout(doneTimer);
      var pos = spots(total);
      var order = buttons.slice().sort(function () { return Math.random() - 0.5; });
      var spot = {};
      order.forEach(function (btn, k) { spot[btn.getAttribute("data-i")] = pos[k]; });
      // DOM (and tab) order follows the visual order: rows of the field top to bottom, then left to right
      var row = 44;
      var sorted = order.slice().sort(function (a, b) {
        var pa = spot[a.getAttribute("data-i")], pb = spot[b.getAttribute("data-i")];
        return (Math.floor(pa[3] / row) - Math.floor(pb[3] / row)) || (pa[2] - pb[2]);
      });
      var move = function () {
        setDone(false);
        sorted.forEach(function (btn) {
          var p = spot[btn.getAttribute("data-i")];
          btn.classList.remove("is-placed");
          btn.disabled = false;
          btn.style.left = p[0] + "%";
          btn.style.top = p[1] + "%";
          field.appendChild(btn);
        });
      };
      if (initial) move();
      else flip(sorted.concat([board]), move);
      buttons = sorted;
      score = 0;
      scoreEl.textContent = pad(score);
    }

    for (var i = 0; i < total; i++) {
      var b = doc.createElement("button");
      b.type = "button";
      b.className = "gpx";
      b.setAttribute("data-i", String(i));
      b.setAttribute("aria-label", pieceName.replace("{n}", String(i + 1)));
      b.setAttribute("data-c", slots[i].getAttribute("data-c")); // light pieces get an edge (CSS)
      b.style.setProperty("--c", slots[i].getAttribute("data-c"));
      b.style.setProperty("--i", String(i));
      b.addEventListener("click", function () { place(this); });
      buttons.push(b);
    }
    scatter(true);

    resetBtn.addEventListener("click", function () {
      scatter(false);
      if (buttons[0]) buttons[0].focus({ preventScroll: true });
    });
  }

  /* ---------------------------------------------------------- how-it-works packets
     One trip down each wire whenever the steps come into view (CSS .is-live), never a loop. */
  function initPackets() {
    var steps = doc.querySelector(".steps");
    if (!steps || !("IntersectionObserver" in window)) return;
    new IntersectionObserver(function (entries) {
      var e = entries[entries.length - 1];
      if (e.intersectionRatio >= 0.35) steps.classList.add("is-live");   // mostly in view: go
      else if (!e.isIntersecting) steps.classList.remove("is-live");    // fully gone: rearm
    }, { threshold: [0, 0.35] }).observe(steps);
  }

  function start() {
    initLanguage();
    initMenu();
    initField();
    initGame();
    initPackets();
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
  else start();
})();
