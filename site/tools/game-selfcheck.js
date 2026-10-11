/* Self-check for the footer game ("Tidy the pixels"). Paste into the browser console on the
   built page, or evaluate it headless (it is one expression that resolves to a report):

     node: await cdp("Runtime.evaluate", { expression: src, awaitPromise: true, returnByValue: true })

   It solves the game and presses "Scatter again" 10 times in a row, then scatters three times
   mid-game and once inside the short pause before "All tidy." appears. After every scatter it
   checks that all 12 pieces are back in the field, none is still placed or disabled, every piece
   has a real position inside the field, no two pieces overlap, the layout differs from the one
   before, the score reads 00, the done message is gone, and (after "Scatter again") focus is on
   a piece. Wait about 30 s for the report: { ok, cycles, errors }. */
(async function gameSelfCheck(cycles) {
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var $ = function (id) { return document.getElementById(id); };
  var game = $("game"), field = $("game-field"), score = $("game-score");
  var done = $("game-done"), reset = $("game-reset"), scatterBtn = $("game-scatter");
  var report = { ok: true, cycles: [], errors: [] };
  if (!game || !field || !score || !done || !reset) return { ok: false, cycles: [], errors: ["game not found"] };
  function fail(msg) { report.ok = false; if (report.errors.length < 40) report.errors.push(msg); }
  function pieces() { return Array.prototype.slice.call(field.querySelectorAll(".gpx")); }

  game.scrollIntoView({ block: "center" });
  await sleep(150);

  function checkScattered(tag, prevKey) {
    var ps = pieces();
    var all = document.querySelectorAll(".gpx");
    if (ps.length !== 12) fail(tag + ": " + ps.length + " pieces in the field (want 12)");
    if (all.length !== 12) fail(tag + ": " + all.length + " pieces on the page (want 12)");
    var ids = {};
    Array.prototype.forEach.call(all, function (b) { ids[b.getAttribute("data-i")] = 1; });
    if (Object.keys(ids).length !== 12) fail(tag + ": duplicate pieces");
    var fr = field.getBoundingClientRect();
    var rects = ps.map(function (b) { return b.getBoundingClientRect(); });
    ps.forEach(function (b, k) {
      var i = b.getAttribute("data-i");
      if (b.classList.contains("is-placed") || b.disabled) fail(tag + ": piece " + i + " is still placed or disabled");
      var l = parseFloat(b.style.left), t = parseFloat(b.style.top);
      if (!isFinite(l) || !isFinite(t)) fail(tag + ": piece " + i + " has no position (left '" + b.style.left + "', top '" + b.style.top + "')");
      var r = rects[k];
      if (r.left < fr.left - 1 || r.right > fr.right + 1 || r.top < fr.top - 1 || r.bottom > fr.bottom + 1) fail(tag + ": piece " + i + " is outside the field");
    });
    for (var a = 0; a < rects.length; a++) {
      for (var c = a + 1; c < rects.length; c++) {
        var A = rects[a], B = rects[c];
        if (A.left < B.right - 0.5 && B.left < A.right - 0.5 && A.top < B.bottom - 0.5 && B.top < A.bottom - 0.5) {
          fail(tag + ": pieces " + ps[a].getAttribute("data-i") + " and " + ps[c].getAttribute("data-i") + " overlap");
        }
      }
    }
    if (score.textContent !== "00") fail(tag + ": score reads " + score.textContent);
    if (!done.hidden || game.classList.contains("is-done")) fail(tag + ": still shows the done state");
    var key = ps.map(function (b) { return b.getAttribute("data-i") + "@" + b.style.left + "," + b.style.top; }).sort().join("|");
    if (prevKey && key === prevKey) fail(tag + ": same layout as before");
    return key;
  }

  async function solve() {
    var ps = pieces();
    for (var k = 0; k < ps.length; k++) { ps[k].click(); await sleep(15); }
    await sleep(1100); // the board waits ~0.5 s for the last piece, then glides
  }

  var key = checkScattered("initial");
  for (var c = 1; c <= (cycles || 10); c++) {
    await solve();
    var solved = game.classList.contains("is-done") && score.textContent === "12" &&
      document.querySelectorAll("#game-slots .gpx").length === 12 && !done.hidden;
    if (!solved) fail("cycle " + c + ": not solved (score " + score.textContent + ")");
    reset.click();
    await sleep(800);
    key = checkScattered("cycle " + c, key);
    var f = document.activeElement;
    if (!f || !f.classList.contains("gpx")) fail("cycle " + c + ": focus is on " + (f ? (f.id || f.className || f.tagName) : "nothing") + " after Scatter again");
    report.cycles.push({ cycle: c, solved: solved });
  }

  if (scatterBtn) {
    for (var m = 1; m <= 3; m++) {
      var some = pieces().slice(0, 4 + m);
      for (var s = 0; s < some.length; s++) { some[s].click(); await sleep(15); }
      await sleep(250);
      if (score.textContent !== String(100 + some.length).slice(1)) fail("mid-game " + m + ": score " + score.textContent);
      scatterBtn.click();
      await sleep(800);
      key = checkScattered("mid-game " + m, key);
    }
    var rest = pieces();
    for (var z = 0; z < rest.length; z++) rest[z].click();
    await sleep(100); // inside the pause before "All tidy."
    scatterBtn.click();
    await sleep(1200); // past the moment the done state would have appeared
    key = checkScattered("scatter during the done pause", key);
  }
  return report;
})(10)
