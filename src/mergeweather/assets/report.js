/* MergeWeather report: interactive graph, clipboard, filters, theme. No dependencies. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var data;
  try { data = JSON.parse(document.getElementById("mw-data").textContent); } catch (_) { return; }

  var COLOR = { pass: "pass", interaction: "inter", fail: "fail", flaky: "flaky", conflict: "conflict",
    error: "error", not_run: "notrun", pending: "notrun", pruned: "pruned" };
  var LABEL = { pass: "☀ Sunny", interaction: "⛈ Thunderstorm", fail: "🌧 Rain", flaky: "🌦 Showers",
    conflict: "🌫 Fog", error: "🌪 Tornado", not_run: "❔ Uncharted", pending: "… Forming", pruned: "✂ Pruned" };
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function anchor(id) { return "combo-" + id.replace(/[^A-Za-z0-9]/g, "-"); }

  /* ---------------- theme ---------------- */
  var themeBtn = document.getElementById("mw-theme");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var dark = document.documentElement.classList.toggle("dark");
    try { localStorage.setItem("mw-theme", dark ? "dark" : "light"); } catch (_) {}
  });

  /* ---------------- clipboard ---------------- */
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (_) {}
    document.body.removeChild(ta);
    return ok ? Promise.resolve() : Promise.reject();
  }
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest(".mw-copy");
    if (!btn) return;
    ev.preventDefault();
    var src = document.getElementById(btn.getAttribute("data-copy"));
    if (!src) return;
    var text = src.textContent;
    var p = navigator.clipboard && window.isSecureContext !== false
      ? navigator.clipboard.writeText(text).catch(function () { return fallbackCopy(text); })
      : fallbackCopy(text);
    var label = btn.querySelector(".mw-copy-label");
    var orig = label.textContent;
    p.then(function () { label.textContent = "Copied ✓"; btn.classList.add("text-emerald-600"); },
           function () { label.textContent = "Press ⌘/Ctrl+C"; selectText(src); })
     .then(function () { setTimeout(function () { label.textContent = orig; btn.classList.remove("text-emerald-600"); }, 1600); });
  });
  function selectText(node) {
    var r = document.createRange(); r.selectNodeContents(node);
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
  }

  /* ---------------- combination filters ---------------- */
  var activeFilter = "all";
  var search = document.getElementById("mw-search");
  function applyFilters() {
    var q = (search && search.value || "").trim().toLowerCase();
    document.querySelectorAll(".mw-row").forEach(function (row) {
      var okS = activeFilter === "all" || row.getAttribute("data-status") === activeFilter;
      var okQ = !q || row.getAttribute("data-id").toLowerCase().indexOf(q) !== -1;
      row.style.display = okS && okQ ? "" : "none";
    });
  }
  document.querySelectorAll(".mw-filter").forEach(function (b) {
    b.addEventListener("click", function () {
      activeFilter = b.getAttribute("data-filter");
      document.querySelectorAll(".mw-filter").forEach(function (x) {
        var on = x === b;
        x.setAttribute("aria-pressed", on);
        x.classList.toggle("bg-zinc-900", on); x.classList.toggle("text-white", on);
        x.classList.toggle("dark:bg-white", on); x.classList.toggle("dark:text-zinc-900", on);
      });
      applyFilters();
    });
  });
  if (search) search.addEventListener("input", applyFilters);

  /* ---------------- graph ---------------- */
  var svg = document.getElementById("mw-graph");
  if (!svg) return;
  var tip = document.getElementById("mw-tip");
  var inspector = document.getElementById("mw-inspector");
  var byId = {};
  data.nodes.forEach(function (n) { byId[n.id] = n; });
  var view = "lattice", focus = null, selected = null, vb = null, bounds = null;
  var nodeEls = {}, edgeEls = [];

  function layoutLattice() {
    var layers = {};
    data.nodes.forEach(function (n) { (layers[n.b.length] = layers[n.b.length] || []).push(n); });
    var sizes = Object.keys(layers).map(Number).sort(function (a, b) { return a - b; });
    var colW = 190, rowH = 54, pos = {};
    var maxRows = Math.max.apply(null, sizes.map(function (k) { return layers[k].length; }));
    sizes.forEach(function (k, i) {
      var list = layers[k].sort(function (a, b) { return a.id < b.id ? -1 : 1; });
      var off = (maxRows - list.length) * rowH / 2;
      list.forEach(function (n, j) { pos[n.id] = { x: 70 + i * colW, y: 40 + off + j * rowH }; });
    });
    var edges = [];
    data.nodes.forEach(function (n) {
      if (!n.b.length) return;
      n.b.forEach(function (drop) {
        var parent = n.b.filter(function (x) { return x !== drop; });
        var pid = parent.length ? parent.join("+") : "base";
        if (byId[pid]) edges.push({ a: pid, b: n.id });
      });
    });
    var nodes = data.nodes.map(function (n) {
      return { id: n.id, x: pos[n.id].x, y: pos[n.id].y, s: n.s, label: n.id, r: n.b.length ? 11 : 14 };
    });
    var cols = sizes.map(function (k, i) { return { x: 70 + i * colW, label: k ? "size " + k : "base" }; });
    return { nodes: nodes, edges: edges, cols: cols };
  }

  function layoutNetwork() {
    var n = data.branches.length, R = 150, cx = 260, cy = 210, nodes = [], edges = [];
    data.branches.forEach(function (b, i) {
      var a = -Math.PI / 2 + 2 * Math.PI * i / Math.max(n, 1);
      var single = byId[b];
      nodes.push({ id: b, x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), s: single ? single.s : "not_run", label: b, r: 16 });
    });
    var pos = {}; nodes.forEach(function (x) { pos[x.id] = x; });
    data.findings.forEach(function (f) {
      if (f.b.length === 1) return;
      if (f.b.length === 2) { edges.push({ a: f.b[0], b: f.b[1], finding: f.id, hot: true, combo: f.combo }); return; }
      var hx = 0, hy = 0;
      f.b.forEach(function (m) { hx += pos[m].x; hy += pos[m].y; });
      var hub = { id: f.combo, x: hx / f.b.length, y: hy / f.b.length, s: "interaction", label: f.id, r: 18, hub: true };
      nodes.push(hub);
      f.b.forEach(function (m) { edges.push({ a: m, b: hub.id, finding: f.id, hot: true, combo: f.combo }); });
    });
    data.conflicts.forEach(function (c) { if (c.length === 2) edges.push({ a: c[0], b: c[1], conflict: true }); });
    return { nodes: nodes, edges: edges, cols: [] };
  }

  function focusSet() {
    if (!focus) return null;
    var f = data.findings.filter(function (x) { return x.id === focus; })[0];
    if (!f) return null;
    var s = {};
    [f.combo, f.from].concat(f.checks, f.steps).forEach(function (id) { s[id] = true; });
    if (view === "network") { f.b.forEach(function (b) { s[b] = true; }); }
    return s;
  }

  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    nodeEls = {}; edgeEls = [];
    var g = view === "lattice" ? layoutLattice() : layoutNetwork();
    var pos = {}; g.nodes.forEach(function (n) { pos[n.id] = n; });
    var fs = focusSet();
    var root = el("g", {}, svg);
    g.cols.forEach(function (c) {
      var t = el("text", { x: c.x, y: 14, "text-anchor": "middle", "font-size": 11, fill: "var(--g-text)", opacity: 0.5 }, root);
      t.textContent = c.label;
    });
    g.edges.forEach(function (ed) {
      var A = pos[ed.a], B = pos[ed.b];
      if (!A || !B) return;
      var hot = ed.hot || (fs && fs[ed.a] && fs[ed.b]);
      var path = el(view === "lattice" ? "path" : "line", view === "lattice"
        ? { d: "M" + A.x + "," + A.y + " C" + (A.x + 80) + "," + A.y + " " + (B.x - 80) + "," + B.y + " " + B.x + "," + B.y }
        : { x1: A.x, y1: A.y, x2: B.x, y2: B.y }, root);
      path.setAttribute("class", "edge");
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", ed.conflict ? "var(--g-conflict)" : hot ? "var(--g-edge-hot)" : "var(--g-edge)");
      path.setAttribute("stroke-width", hot ? 2.5 : 1.25);
      if (ed.conflict) path.setAttribute("stroke-dasharray", "6 5");
      if (fs && !hot) path.classList.add("dim");
      edgeEls.push({ el: path, a: ed.a, b: ed.b });
    });
    g.nodes.forEach(function (n) {
      var grp = el("g", { class: "node", transform: "translate(" + n.x + "," + n.y + ")", tabindex: 0,
        role: "button", "aria-label": n.label + " " + (LABEL[n.s] || n.s) }, root);
      var col = "var(--g-" + (COLOR[n.s] || "notrun") + ")";
      if (n.s === "interaction" || n.hub) el("circle", { r: n.r + 7, fill: col, opacity: 0.18 }, grp);
      el("circle", { r: n.r, fill: n.s === "pruned" ? "var(--g-bg)" : col, stroke: n.s === "pruned" ? col : "var(--g-bg)",
        "stroke-width": 2, "stroke-dasharray": n.s === "pruned" ? "3 3" : "" }, grp);
      if (fs && fs[n.id]) el("circle", { r: n.r + 4, fill: "none", stroke: "var(--g-ring)", "stroke-width": 2 }, grp);
      var t = el("text", { x: view === "lattice" ? n.r + 6 : 0, y: view === "lattice" ? 4 : -(n.r + 8),
        "text-anchor": view === "lattice" ? "start" : "middle", "font-size": n.hub ? 12 : 11,
        "font-family": "ui-monospace,Menlo,monospace", fill: "var(--g-text)", "font-weight": n.hub ? 700 : 400 }, grp);
      t.textContent = n.label;
      if (fs && !fs[n.id]) grp.classList.add("dim");
      nodeEls[n.id] = grp;
      grp.addEventListener("mouseenter", function (ev) { showTip(n, ev); highlight(n.id); });
      grp.addEventListener("mousemove", moveTip);
      grp.addEventListener("mouseleave", function () { tip.classList.add("hidden"); highlight(null); });
      grp.addEventListener("click", function (ev) { ev.stopPropagation(); inspect(n); });
      grp.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); inspect(n); } });
    });
    var bb = root.getBBox();
    bounds = { x: bb.x - 40, y: bb.y - 30, w: Math.max(bb.width + 80, 300), h: Math.max(bb.height + 60, 200) };
    fit();
  }

  function highlight(id) {
    if (focus) return;
    if (!id) {
      Object.keys(nodeEls).forEach(function (k) { nodeEls[k].classList.remove("dim"); });
      edgeEls.forEach(function (e) { e.el.classList.remove("dim"); });
      return;
    }
    var keep = {}; keep[id] = true;
    edgeEls.forEach(function (e) {
      var on = e.a === id || e.b === id;
      if (on) { keep[e.a] = true; keep[e.b] = true; }
      e.el.classList.toggle("dim", !on);
    });
    Object.keys(nodeEls).forEach(function (k) { nodeEls[k].classList.toggle("dim", !keep[k]); });
  }

  function nodeInfo(n) {
    var d = byId[n.id] || {};
    var f = data.findings.filter(function (x) { return x.combo === n.id; })[0];
    var html = '<div class="font-mono text-sm font-semibold">' + esc(n.id) + "</div>" +
      '<div class="mt-1">' + esc(LABEL[n.s] || n.s) + "</div>";
    if (d.runs !== undefined) html += '<div class="mt-1 opacity-70">' + d.runs + " run(s)" + (d.tree ? " · tree " + esc(d.tree) : "") + "</div>";
    if (d.fp && d.fp.length) html += '<div class="mt-1 font-mono opacity-70">' + esc(d.fp.join(", ")) + "</div>";
    if (d.conf && d.conf.length) html += '<div class="mt-1">conflict in ' + esc(d.conf.join(", ")) + "</div>";
    if (d.why) html += '<div class="mt-1 opacity-70">' + esc(d.why) + "</div>";
    if (f) html += '<div class="mt-1 font-semibold text-rose-500">' + esc(f.id + " · " + f.kind + " · " + f.min) + "</div>";
    return { html: html, finding: f, data: d };
  }
  function showTip(n, ev) { tip.innerHTML = nodeInfo(n).html; tip.classList.remove("hidden"); moveTip(ev); }
  function moveTip(ev) {
    var r = svg.getBoundingClientRect();
    var x = ev.clientX - r.left + 14, y = ev.clientY - r.top + 14;
    if (x + 240 > r.width) x = ev.clientX - r.left - 250;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function inspect(n) {
    var info = nodeInfo(n);
    var links = "";
    if (info.data.runs !== undefined || info.data.conf) links += '<a class="mt-3 inline-block text-sky-500 hover:underline" href="#' + anchor(n.id) + '" data-open="' + anchor(n.id) + '">Open evidence →</a>';
    if (info.finding) links += '<br><a class="mt-1 inline-block text-rose-500 hover:underline" href="#finding-' + esc(info.finding.id) + '">Go to ' + esc(info.finding.id) + " →</a>";
    inspector.innerHTML = '<div class="text-xs uppercase tracking-wide opacity-60">Selected</div><div class="mt-2 text-xs">' + info.html + "</div>" + links;
  }
  inspector.addEventListener("click", function (ev) {
    var a = ev.target.closest("[data-open]");
    if (a) { var d = document.getElementById(a.getAttribute("data-open")); if (d) d.open = true; }
  });

  /* pan & zoom via viewBox */
  function setVB() { svg.setAttribute("viewBox", [vb.x, vb.y, vb.w, vb.h].join(" ")); }
  function fit() { vb = { x: bounds.x, y: bounds.y, w: bounds.w, h: bounds.h }; setVB(); }
  function zoom(f, cx, cy) {
    var nw = vb.w / f, nh = vb.h / f;
    if (nw > bounds.w * 4 || nw < 80) return;
    cx = cx === undefined ? vb.x + vb.w / 2 : cx; cy = cy === undefined ? vb.y + vb.h / 2 : cy;
    vb = { x: cx - (cx - vb.x) / f, y: cy - (cy - vb.y) / f, w: nw, h: nh }; setVB();
  }
  function toSvg(ev) {
    var r = svg.getBoundingClientRect();
    var s = Math.max(vb.w / r.width, vb.h / r.height);
    var ox = (r.width * s - vb.w) / 2, oy = (r.height * s - vb.h) / 2;
    return { x: vb.x - ox + (ev.clientX - r.left) * s, y: vb.y - oy + (ev.clientY - r.top) * s, s: s };
  }
  svg.addEventListener("wheel", function (ev) {
    ev.preventDefault(); var p = toSvg(ev); zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y);
  }, { passive: false });
  var drag = null;
  svg.addEventListener("pointerdown", function (ev) {
    if (ev.target.closest(".node")) return;
    drag = { x: ev.clientX, y: ev.clientY, vx: vb.x, vy: vb.y, s: toSvg(ev).s };
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!drag) return;
    vb.x = drag.vx - (ev.clientX - drag.x) * drag.s; vb.y = drag.vy - (ev.clientY - drag.y) * drag.s; setVB();
  });
  svg.addEventListener("pointerup", function () { drag = null; });
  document.querySelectorAll(".mw-zoom").forEach(function (b) {
    b.addEventListener("click", function () { var f = +b.getAttribute("data-zoom"); f ? zoom(f) : fit(); });
  });

  document.querySelectorAll(".mw-view").forEach(function (b) {
    b.addEventListener("click", function () { view = b.getAttribute("data-view"); syncButtons(); draw(); });
  });
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest(".mw-focus");
    if (!b) return;
    focus = b.getAttribute("data-focus") || null;
    if (focus && !b.closest("#graph")) document.getElementById("graph").scrollIntoView({ behavior: "smooth" });
    syncButtons(); draw();
    var f = data.findings.filter(function (x) { return x.id === focus; })[0];
    if (f) inspect({ id: f.combo, s: byId[f.combo] ? byId[f.combo].s : "interaction" });
  });
  function syncButtons() {
    document.querySelectorAll(".mw-view").forEach(function (b) {
      var on = b.getAttribute("data-view") === view;
      b.setAttribute("aria-pressed", on);
      b.classList.toggle("bg-zinc-900", on); b.classList.toggle("text-white", on);
      b.classList.toggle("dark:bg-zinc-100", on); b.classList.toggle("dark:text-zinc-900", on);
    });
    document.querySelectorAll("#graph .mw-focus").forEach(function (b) {
      b.classList.toggle("ring-2", (b.getAttribute("data-focus") || null) === focus && !!focus);
      b.classList.toggle("ring-sky-500", (b.getAttribute("data-focus") || null) === focus && !!focus);
    });
  }
  syncButtons();
  draw();
  if (data.findings.length) { focus = data.findings[0].id; syncButtons(); draw(); }
})();
