/* tidy-one site: theme, menu, hero pixel field and mascot, footer game. No dependencies. */
(function () {
  "use strict";

  var doc = document;
  var root = doc.documentElement;
  var THEME_KEY = "tidy-one:theme";
  function query(q) {
    return window.matchMedia ? window.matchMedia(q) : { matches: false };
  }
  function listen(mq, fn) {
    if (mq.addEventListener) mq.addEventListener("change", fn);
    else if (mq.addListener) mq.addListener(fn);
  }
  var reduceMotion = query("(prefers-reduced-motion: reduce)");
  var darkQuery = query("(prefers-color-scheme: dark)");

  /* Reduced motion can be switched on while something moves. The change event does not always
     arrive, so the loops call reduced() too: whichever notices the switch first runs every
     handler once (stop, draw the still state, rest the mascot). */
  var reducedSeen = !!reduceMotion.matches;
  var reducedHandlers = [];
  function onReduced(fn) { reducedHandlers.push(fn); }
  function reduced() {
    var now = !!reduceMotion.matches;
    if (now !== reducedSeen) {
      reducedSeen = now;
      for (var i = 0; i < reducedHandlers.length; i++) reducedHandlers[i](now);
    }
    return now;
  }
  listen(reduceMotion, reduced);

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch (e) {
      return null;
    }
    return null;
  }

  /* ---------------------------------------------------------- theme
     The system preference is the default; the toggle overrides it and remembers the choice.
     Toggling back to what the system asks for forgets the choice, so the page follows the
     system again. The inline script in <head> applies a stored choice before the first paint. */
  var themeListeners = [];
  function onTheme(fn) { themeListeners.push(fn); }
  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t === "light" || t === "dark") return t;
    return darkQuery.matches ? "dark" : "light";
  }

  function initTheme() {
    var btn = doc.getElementById("theme-toggle");
    var metas = doc.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i++) {
      metas[i].setAttribute("data-media", metas[i].getAttribute("media") || "");
      metas[i].setAttribute("data-content", metas[i].getAttribute("content") || "");
    }
    function sync() {
      var dark = currentTheme() === "dark";
      if (btn) btn.setAttribute("aria-pressed", dark ? "true" : "false");
      // an explicit choice colours the browser chrome too
      var explicit = root.hasAttribute("data-theme");
      for (var k = 0; k < metas.length; k++) {
        var m = metas[k];
        if (explicit) {
          m.removeAttribute("media");
          m.setAttribute("content", dark ? "#1E2A2F" : "#F8F9F7");
        } else {
          if (m.getAttribute("data-media")) m.setAttribute("media", m.getAttribute("data-media"));
          m.setAttribute("content", m.getAttribute("data-content"));
        }
      }
    }
    function changed() {
      sync();
      for (var k = 0; k < themeListeners.length; k++) themeListeners[k]();
    }
    if (btn) {
      btn.addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        var system = darkQuery.matches ? "dark" : "light";
        if (next === system) {
          root.removeAttribute("data-theme");
          store(THEME_KEY, null);
        } else {
          root.setAttribute("data-theme", next);
          store(THEME_KEY, next);
        }
        changed();
      });
    }
    listen(darkQuery, function () {
      if (!root.hasAttribute("data-theme")) changed();
    });
    sync();
  }

  /* ---------------------------------------------------------- menu */
  function initMenu() {
    var btn = doc.querySelector(".menu-btn");
    var menu = doc.getElementById("site-menu");
    if (!btn || !menu) return;
    // Narrow screens draw brand | Menu | theme, with the open menu on a row below, so the
    // toggle moves in front of the menu in the DOM and focus follows that order; wide screens
    // draw the links first, so it goes back after them.
    var toggle = doc.getElementById("theme-toggle");
    var narrow = query("(max-width: 900px)");
    function placeToggle() {
      if (!toggle || toggle.parentNode !== menu.parentNode) return;
      var want = narrow.matches ? menu : null;
      if (toggle.nextElementSibling === want) return;
      var hadFocus = doc.activeElement === toggle;
      menu.parentNode.insertBefore(toggle, want);
      if (hadFocus) toggle.focus({ preventScroll: true });
    }
    placeToggle();
    listen(narrow, placeToggle);
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

  /* ---------------------------------------------------------- mascot poses */
  function poser(box) {
    var use = box && box.querySelector("use");
    var cur = use ? (use.getAttribute("href") || "").replace("#m-", "") : "";
    return function (pose) {
      if (!use || pose === cur) return;
      cur = pose;
      use.setAttribute("href", "#m-" + pose);
    };
  }

  /* A wave is two frames swapped a few times (about 1.3 s), then the first frame holds.
     With reduced motion the hand is simply raised. */
  function waveFrames(apply) {
    var timer = 0, n = 0;
    function stop() {
      if (timer) { window.clearInterval(timer); timer = 0; }
    }
    return {
      start: function () {
        stop();
        n = 0;
        apply(0);
        if (reduceMotion.matches) return;
        timer = window.setInterval(function () {
          n++;
          apply(n % 2);
          if (n >= 6) { stop(); apply(0); }
        }, 220);
      },
      stop: function () { stop(); apply(0); }
    };
  }

  /* The hero mascot: idle, blinking now and then (a few blinks, then it rests until the reader
     does something), waving while the reader points at it or at a call to action, and sweeping
     while the field tidies (two broom frames swapped by scroll progress, sliding a few art
     pixels). No blinking or sliding with reduced motion. */
  function initHeroMascot() {
    var box = doc.getElementById("hero-mascot");
    if (!box) return null;
    var setPose = poser(box);
    var svg = box.querySelector("svg");
    var state = { wave: 0, waveFrame: 0, blink: false, sweep: 0 };
    var MAX_BLINKS = 4;
    var blinks = 0, blinkTimer = 0, openTimer = 0, visible = true, mpx = 4, sweepArt = 10;

    function render() {
      setPose(state.wave ? (state.waveFrame ? "wave2" : "wave") : state.sweep === 1 ? "tidy" : state.sweep === 2 ? "tidy2" : state.blink ? "blink" : "idle");
    }
    var waver = waveFrames(function (f) { state.waveFrame = f; render(); });
    function measure() {
      var w = svg ? svg.getBoundingClientRect().width : 0;
      mpx = w ? Math.round(w / 40) || 1 : 4;
      // how far it may slide while sweeping (art pixels; less where the buttons stand beside it)
      sweepArt = parseFloat(window.getComputedStyle(box).getPropertyValue("--sweep-art")) || 10;
    }

    function scheduleBlink() {
      window.clearTimeout(blinkTimer);
      blinkTimer = 0;
      if (reduceMotion.matches || !visible || doc.hidden || blinks >= MAX_BLINKS) return;
      blinkTimer = window.setTimeout(function () {
        blinkTimer = 0;
        blinks++;
        state.blink = true;
        render();
        openTimer = window.setTimeout(function () {
          state.blink = false;
          render();
          scheduleBlink();
        }, 150);
      }, 2400 + Math.random() * 2600);
    }
    function wake() {
      if (blinks >= MAX_BLINKS || !blinkTimer) {
        if (blinks >= MAX_BLINKS) blinks = 0;
        if (!blinkTimer && !state.blink) scheduleBlink();
      }
    }

    // wave: each source (pointer on the mascot, pointer on or focus in the calls to action)
    function waveFrom(on) {
      var was = state.wave;
      state.wave = Math.max(0, state.wave + (on ? 1 : -1));
      if (!was && state.wave) waver.start();
      else if (was && !state.wave) waver.stop();
      render();
    }
    function hoverable(el) {
      var inside = false;
      el.addEventListener("pointerenter", function () { if (!inside) { inside = true; waveFrom(true); } });
      el.addEventListener("pointerleave", function () { if (inside) { inside = false; waveFrom(false); } });
    }
    hoverable(box);
    var ctas = doc.querySelectorAll(".hero .cta-row a");
    for (var i = 0; i < ctas.length; i++) {
      hoverable(ctas[i]);
      ctas[i].addEventListener("focus", function () { waveFrom(true); });
      ctas[i].addEventListener("blur", function () { waveFrom(false); });
    }

    doc.addEventListener("visibilitychange", function () {
      if (doc.hidden) { window.clearTimeout(blinkTimer); blinkTimer = 0; }
      else wake();
    });
    var hero = box.closest(".hero");
    if (hero) hero.addEventListener("pointermove", wake, { passive: true });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        if (visible) wake();
        else { window.clearTimeout(blinkTimer); blinkTimer = 0; }
      }).observe(box);
    }
    onReduced(function (on) {
      if (on) {
        window.clearTimeout(blinkTimer);
        window.clearTimeout(openTimer);
        blinkTimer = 0;
        waver.stop();
        state.blink = false;
        state.sweep = 0;
        box.style.removeProperty("--sweep");
        render();
      } else {
        wake();
      }
    });
    if ("ResizeObserver" in window) new ResizeObserver(measure).observe(box);
    measure();
    scheduleBlink();

    return {
      // P: the field's tidy progress, 0 (scattered) to 1 (tidy)
      progress: function (P) {
        if (reduced()) return;
        state.sweep = P > 0.015 && P < 0.985 ? 1 + (Math.floor(P * 36) % 2) : 0;
        // out and back: it slides left while sweeping and is home again once the field is tidy
        box.style.setProperty("--sweep", -Math.round(Math.sin(P * Math.PI) * sweepArt) * mpx + "px");
        render();
        wake();
      }
    };
  }

  /* ---------------------------------------------------------- hero pixel field
     Scattered: pixels hang from the hairline in loose clouds with ragged, dissolving edges,
     slightly off the grid and slightly smaller. Scrolling tidies them in a wave from left to
     right: each pixel travels to its own cell and clicks into place, filling 3 x 3 tiles sorted
     from the darkest tone to mist. On the dark theme a soft bloom sits under the pixels: they are
     drawn once more, larger, into a canvas at a fifth of the size and blurred there; that small
     canvas is the page element behind the pixels, so the browser scales it up (no full-size
     upscale on the main thread). The light theme has no bloom (on paper it can only darken).
     Colours come from CSS custom properties and are read again when the theme changes.
     The loop runs only while something moves: while the field catches up with the scroll, plus
     a slow, short drift (~10 fps, under 5 s) after load or a scroll, then it sleeps. */
  function initField(mascot) {
    var canvas = doc.getElementById("tidy-grid");
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var hero = canvas.closest(".hero") || root;

    var TONE_STEPS = [0.22, 0.42, 0.62, 0.82];
    var DUR = 0.32;       // share of the scroll range one pixel spends travelling
    var WAVE = 0.62;      // pixels set off in a wave from left to right over this share
    var SNAP = 0.9;       // point of the trip where a pixel clicks into its cell
    var DRIFT_MS = 4800;  // idle drift after load or the last scroll (under 5 s, WCAG 2.2.2)
    var FADE_MS = 1500;   // the drift eases out over this long before the loop sleeps
    var GLOW_SCALE = 5;   // CSS pixels per glow pixel
    // how strongly each tone blooms (darkest first). Each pixel glows in its own tone, and the
    // light tones are weighted down so the mist on the right glows no more than the sage
    var GLOW_WEIGHTS = [0.55, 0.5, 0.42, 0.3, 0.22];

    var colors = { tones: ["#2F3E46", "#354F52", "#52796F", "#84A98C", "#CAD2C5"], empty: "rgba(202,210,197,.32)",
      glowAlpha: 0 };

    var W = 0, H = 0, dpr = 1, cell = 12, gap = 2, cols = 0, rows = 0, ox = 0;
    var px = [], bg = null, XS, YS, SS, AS;
    var glowEl = doc.getElementById("tidy-glow");
    var outCtx = glowEl && glowEl.getContext ? glowEl.getContext("2d") : null;
    var glow = null, glowCtx = null, gw = 0, gh = 0, glowShown = false;
    if (outCtx && !("filter" in outCtx)) glowEl.style.filter = "blur(8px)"; // no canvas filter: blur the element
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

    function readColors() {
      var cs = window.getComputedStyle(root);
      function v(name, fallback) { return (cs.getPropertyValue(name) || "").trim() || fallback; }
      for (var i = 0; i < 5; i++) colors.tones[i] = v("--px-" + i, colors.tones[i]);
      colors.empty = v("--px-empty", colors.empty);
      colors.glowAlpha = parseFloat(v("--px-glow-alpha", "0")) || 0;
    }

    function paintGrid() {
      // faint empty grid, drawn once per size or theme
      bg = bg || doc.createElement("canvas");
      bg.width = canvas.width;
      bg.height = canvas.height;
      var g = bg.getContext("2d");
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, bg.width, bg.height);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.fillStyle = colors.empty;
      for (var yy = 0; yy < rows; yy++) {
        for (var xx = 0; xx < cols; xx++) g.fillRect(ox + xx * cell, yy * cell, cell - gap, cell - gap);
      }
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

      // 1. tidy end state: 3 x 3 tiles with one-cell gutters filling the field
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

      // 2. scattered start: clouds hanging from the top edge with a ragged lower edge, open
      //    pockets inside and a thin trail of pixels dissolving below
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
          sx: sp.x + (rand() - 0.5) * 0.6,
          sy: sp.y + (rand() - 0.5) * 0.6,
          sz: 0.6 + 0.3 * d + 0.08 * rand(),
          a: 0.45 + 0.55 * Math.min(1, d * 1.6),
          d: WAVE * (0.82 * h.hx / Math.max(1, cols) + 0.18 * rand()),
          ph: rand() * 6.283, sp: 0.7 + rand() * 0.6
        });
      }
      px.sort(function (a, b) { return a.c - b.c; });
      XS = new Float32Array(n);
      YS = new Float32Array(n);
      SS = new Float32Array(n);
      AS = new Float32Array(n);

      // bloom at a fifth of the size: sharp squares into a buffer, blurred into the page element
      gw = Math.max(1, Math.ceil(W / GLOW_SCALE));
      gh = Math.max(1, Math.ceil(H / GLOW_SCALE));
      if (outCtx) {
        glow = glow || doc.createElement("canvas");
        glow.width = gw;
        glow.height = gh;
        glowCtx = glow.getContext("2d");
        glowEl.width = gw;
        glowEl.height = gh;
        glowShown = true;
      }
      paintGrid();
    }

    function drawGlow(n) {
      if (!glowCtx || !outCtx) return;
      if (colors.glowAlpha <= 0) {
        if (glowShown) { outCtx.clearRect(0, 0, gw, gh); glowShown = false; }
        return;
      }
      glowShown = true;
      var g = glowCtx;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.globalAlpha = 1;
      g.clearRect(0, 0, gw, gh);
      g.setTransform(gw / W, 0, 0, gh / H, 0, 0);
      var pad = cell * 0.3, lastC = -1, lastA = -1;
      for (var i = 0; i < n; i++) {
        if (SS[i] <= 0) continue;
        var c = px[i].c;
        var a = Math.round(GLOW_WEIGHTS[c] * AS[i] * 10) / 10;
        if (a <= 0) continue;
        if (a !== lastA) { g.globalAlpha = a; lastA = a; }
        if (c !== lastC) { g.fillStyle = colors.tones[c]; lastC = c; }
        g.fillRect(XS[i] - pad, YS[i] - pad, SS[i] + pad * 2, SS[i] + pad * 2);
      }
      outCtx.setTransform(1, 0, 0, 1, 0, 0);
      outCtx.clearRect(0, 0, gw, gh);
      if ("filter" in outCtx) outCtx.filter = "blur(1.6px)";
      outCtx.globalAlpha = colors.glowAlpha;
      outCtx.drawImage(glow, 0, 0);
      outCtx.globalAlpha = 1;
      if ("filter" in outCtx) outCtx.filter = "none";
    }

    function draw(now, live) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (bg) ctx.drawImage(bg, 0, 0);
      var still = reducedSeen;
      var s = cell - gap;
      var amp = still ? 0 : 0.22 * live;
      var n = px.length;
      // positions first: the bloom and the pixels use the same ones
      for (var i = 0; i < n; i++) {
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
        var off = X >= W || Y >= H || X + size <= 0 || Y + size <= 0;
        XS[i] = X;
        YS[i] = Y;
        SS[i] = off ? 0 : size;
        AS[i] = Math.round(a * 10) / 10;
      }
      drawGlow(n);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var lastColor = -1, lastAlpha = -1;
      for (var k = 0; k < n; k++) {
        if (SS[k] <= 0) continue;
        if (AS[k] !== lastAlpha) { ctx.globalAlpha = AS[k]; lastAlpha = AS[k]; }
        if (px[k].c !== lastColor) { ctx.fillStyle = colors.tones[px[k].c]; lastColor = px[k].c; }
        ctx.fillRect(XS[k], YS[k], SS[k], SS[k]);
      }
      ctx.globalAlpha = 1;
    }

    function setTidy() {
      var v = P.toFixed(2);
      if (v !== tidyOut) {
        tidyOut = v;
        hero.style.setProperty("--tidy", v);
        if (mascot) mascot.progress(P);
      }
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
      if (reduced()) return; // switched on mid-motion: the handler has drawn the still field
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

    readColors();
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
      if (reduced()) return; // already drawn tidy; nothing changes on scroll
      measure();
      idleUntil = performance.now() + DRIFT_MS;
      kick();
    }, { passive: true });

    // new colours: repaint the grid and the frame as it is (no new motion)
    onTheme(function () {
      var still = reduced();
      readColors();
      paintGrid();
      draw(performance.now(), still ? 0 : clamp((idleUntil - performance.now()) / FADE_MS, 0, 1));
    });

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

    onReduced(function (on) {
      stop();
      if (on) { drawStill(); return; }
      measure();
      P = target;
      idleUntil = performance.now() + DRIFT_MS;
      draw(performance.now(), 1);
      kick();
    });
  }

  /* ---------------------------------------------------------- footer game
     Twelve pixel buttons scattered over a field; each click, tap or Enter/Space sends one to its
     slot. "Scatter again" (after a win, or the scatter button at any time) puts every piece back
     into the field at fresh random, non-overlapping spots and resets the count. */
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
    var scatterBtn = doc.getElementById("game-scatter");
    var setHost = poser(doc.getElementById("game-host"));
    var hostWave = waveFrames(function (f) { setHost(f ? "wave2" : "wave"); });
    var pieceName = game.getAttribute("data-piece") || "{n}";
    var doneText = game.getAttribute("data-done") || "";
    var total = slots.length;
    var SIZE = 34, ROW = 44;
    var score = 0;
    var buttons = [];
    var doneTimer = 0, hostTimer = 0;

    function pad(n) { return (n < 10 ? "0" : "") + n; }
    function animates() { return !reduceMotion.matches && !!board.animate; }

    // FLIP: measure, change the layout, then animate every element from where it was
    function flip(els, mutate) {
      var first = els.map(function (el) { return el.getBoundingClientRect(); });
      // a new move starts from where things are now; drop any trip still under way
      els.forEach(function (el) {
        if (el.getAnimations) el.getAnimations().forEach(function (a) { a.cancel(); });
      });
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

    function shuffle(list) {
      for (var i = list.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var t = list[i]; list[i] = list[j]; list[j] = t;
      }
      return list;
    }

    // n non-overlapping spots: shuffle the cells of a coarse grid over the field and jitter
    // each piece inside its own cell. Measured on the visible field (the caller makes sure).
    function spots(n) {
      var fw = field.clientWidth || field.getBoundingClientRect().width;
      var fh = field.clientHeight || field.getBoundingClientRect().height;
      var out = [];
      if (fw < SIZE || fh < SIZE) {
        for (var z = 0; z < n; z++) out.push([Math.random() * 90, Math.random() * 80, 0, z * ROW]);
        return out;
      }
      var cw = SIZE + 12, ch = SIZE + 10;
      var cols = Math.max(1, Math.floor(fw / cw)), rows = Math.max(1, Math.floor(fh / ch));
      var cells = [];
      for (var c = 0; c < cols * rows; c++) cells.push(c);
      shuffle(cells);
      var sx = fw / cols, sy = fh / rows;
      for (var i = 0; i < n; i++) {
        var x, y;
        if (i < cells.length) {
          var cx = cells[i] % cols, cy = Math.floor(cells[i] / cols);
          x = cx * sx + Math.random() * Math.max(0, sx - SIZE);
          y = cy * sy + Math.random() * Math.max(0, sy - SIZE);
        } else {
          x = Math.random() * (fw - SIZE);
          y = Math.random() * (fh - SIZE);
        }
        x = Math.min(x, fw - SIZE);
        y = Math.min(y, fh - SIZE);
        out.push([x / fw * 100, y / fh * 100, x, y]);
      }
      return out;
    }

    function hostPose(pose, ms) {
      window.clearTimeout(hostTimer);
      hostWave.stop();
      if (pose === "wave") hostWave.start();
      else setHost(pose);
      if (ms) hostTimer = window.setTimeout(function () { setHost(game.classList.contains("is-done") ? "wave" : "idle"); }, ms);
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
        hostPose("wave");
      } else {
        game.classList.remove("is-done");
        doneEl.hidden = true;
        stage.style.minHeight = "";
        liveEl.textContent = "";
        hostPose("idle");
      }
    }

    function render(focusReset) {
      scoreEl.textContent = pad(score);
      if (score !== total) return;
      window.clearTimeout(doneTimer);
      // let the last pixel land before the board moves; the reset button exists only then
      doneTimer = window.setTimeout(function () {
        doneTimer = 0;
        setDone(true);
        // unless the reader has moved on meanwhile, focus goes from the game to the reset button
        var at = doc.activeElement;
        if (focusReset && (at === game || at === doc.body || !at)) resetBtn.focus({ preventScroll: true });
      }, animates() ? 480 : 0);
    }

    function place(btn) {
      if (btn.classList.contains("is-placed") || btn.disabled) return;
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
      if (score < total && !reduceMotion.matches) hostPose("tidy", 320);
      render(hadFocus && !next);
    }

    function scatter(initial) {
      window.clearTimeout(doneTimer);
      doneTimer = 0;
      var all = buttons.slice();
      var move = function () {
        // The field is hidden while the board shows "All tidy", so it must be visible again
        // before it is measured: measuring a hidden field gave every piece a NaN position and
        // they all piled up in its corner.
        setDone(false);
        var pos = spots(total);
        var order = shuffle(all.slice());
        var spot = {};
        order.forEach(function (btn, k) { spot[btn.getAttribute("data-i")] = pos[k]; });
        // DOM (and tab) order follows the visual order: rows of the field top to bottom, then left to right
        var sorted = order.slice().sort(function (a, b) {
          var pa = spot[a.getAttribute("data-i")], pb = spot[b.getAttribute("data-i")];
          return (Math.floor(pa[3] / ROW) - Math.floor(pb[3] / ROW)) || (pa[2] - pb[2]);
        });
        sorted.forEach(function (btn) {
          var p = spot[btn.getAttribute("data-i")];
          btn.classList.remove("is-placed");
          btn.disabled = false;
          btn.style.left = p[0].toFixed(3) + "%";
          btn.style.top = p[1].toFixed(3) + "%";
          field.appendChild(btn);
        });
        buttons = sorted;
      };
      if (initial) move();
      else flip(all.concat([board]), move);
      score = 0;
      scoreEl.textContent = pad(score);
    }

    for (var i = 0; i < total; i++) {
      var b = doc.createElement("button");
      b.type = "button";
      b.className = "gpx";
      b.setAttribute("data-i", String(i));
      b.setAttribute("aria-label", pieceName.replace("{n}", String(i + 1)));
      b.setAttribute("data-t", slots[i].getAttribute("data-t"));
      b.style.setProperty("--i", String(i));
      b.addEventListener("click", function () { place(this); });
      buttons.push(b);
    }
    scatter(true);

    // after a win the reset button disappears with the board, so focus goes to the first piece
    resetBtn.addEventListener("click", function () {
      scatter(false);
      if (buttons[0]) buttons[0].focus({ preventScroll: true });
    });
    // the scatter button stays where it is, so it keeps focus
    if (scatterBtn) scatterBtn.addEventListener("click", function () { scatter(false); });
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
    initTheme();
    initMenu();
    initField(initHeroMascot());
    initGame();
    initPackets();
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
  else start();
})();
