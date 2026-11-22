// The builder's canvas: inline SVG, one script. Every change is saved to the server (PUT /api/builds/<id>/shapes).
(function () {
  const root = document.getElementById('builder');
  if (!root) return;
  const BID = root.dataset.build;
  const LEVEL = +root.dataset.level;
  const MAX = +root.dataset.max || 16;
  const STEP = LEVEL <= 2 ? 1 : (LEVEL <= 5 ? 0.5 : 0.25);
  const FILL = { red: '#c82d26', blue: '#2350b4', yellow: '#f0be1e', green: '#248c46', black: '#1e1e22' };
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.getElementById('board');
  const $ = (id) => document.getElementById(id);

  let shapes = JSON.parse(root.dataset.shapes || '[]');
  let sel = -1, tool = 'rect', color = 'red', snapOn = true, showGrid = root.dataset.grid === 'True';
  let drag = null, tri = [], hover = null;
  const history = [];
  let saveTimer = null, saving = Promise.resolve();

  // ------------------------------------------------------------ geometry
  const q8 = (v) => Math.round(v * 8) / 8;
  const snap = (v) => Math.min(10, Math.max(0, snapOn ? Math.round(v / STEP) * STEP : q8(v)));
  const fmt = (v) => String(+(+v).toFixed(3));
  const Y = (y) => 10 - y;

  function bbox(s) {
    if (s.shape === 'rect') return [s.x, s.y, s.x + s.w, s.y + s.h];
    if (s.shape === 'ellipse') return [s.cx - s.rx, s.cy - s.ry, s.cx + s.rx, s.cy + s.ry];
    const xs = s.points.map(p => p[0]), ys = s.points.map(p => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  function inside(s, x, y) {
    if (s.shape === 'rect') return x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h;
    if (s.shape === 'ellipse') return ((x - s.cx) / s.rx) ** 2 + ((y - s.cy) / s.ry) ** 2 <= 1;
    const [a, b, c] = s.points;
    const e = (p, q) => (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]);
    const d1 = e(a, b), d2 = e(b, c), d3 = e(c, a);
    return (d1 >= 0 && d2 >= 0 && d3 >= 0) || (d1 <= 0 && d2 <= 0 && d3 <= 0);
  }
  function handles(s) {
    if (s.shape === 'triangle') return s.points.map((p, i) => ({ id: i, x: p[0], y: p[1] }));
    const [x0, y0, x1, y1] = bbox(s);
    return [{ id: 'bl', x: x0, y: y0 }, { id: 'br', x: x1, y: y0 }, { id: 'tr', x: x1, y: y1 }, { id: 'tl', x: x0, y: y1 }];
  }
  function fromBox(kind, c, x0, y0, x1, y1) {
    const a = Math.min(x0, x1), b = Math.min(y0, y1), w = Math.abs(x1 - x0), h = Math.abs(y1 - y0);
    if (kind === 'rect') return { shape: 'rect', color: c, x: a, y: b, w, h };
    return { shape: 'ellipse', color: c, cx: a + w / 2, cy: b + h / 2, rx: w / 2, ry: h / 2 };
  }
  function clampInside(s) {
    const [x0, y0, x1, y1] = bbox(s);
    const dx = x0 < 0 ? -x0 : (x1 > 10 ? 10 - x1 : 0), dy = y0 < 0 ? -y0 : (y1 > 10 ? 10 - y1 : 0);
    return dx || dy ? shifted(s, dx, dy) : s;
  }
  function shifted(s, dx, dy) {
    if (s.shape === 'rect') return { ...s, x: s.x + dx, y: s.y + dy };
    if (s.shape === 'ellipse') return { ...s, cx: s.cx + dx, cy: s.cy + dy };
    return { ...s, points: s.points.map(p => [p[0] + dx, p[1] + dy]) };
  }
  function describe(s) {
    if (s.shape === 'rect') return `rect ${s.color} ${fmt(s.x)} ${fmt(s.y)} ${fmt(s.w)} ${fmt(s.h)}`;
    if (s.shape === 'ellipse') return `ellipse ${s.color} ${fmt(s.cx)} ${fmt(s.cy)} ${fmt(s.rx)} ${fmt(s.ry)}`;
    return `triangle ${s.color} ` + s.points.map(p => fmt(p[0]) + ' ' + fmt(p[1])).join(' ');
  }
  function valid(s) {
    const [x0, y0, x1, y1] = bbox(s);
    if (x0 < -1e-9 || y0 < -1e-9 || x1 > 10 + 1e-9 || y1 > 10 + 1e-9) return false;
    if (s.shape === 'rect') return s.w > 0 && s.h > 0;
    if (s.shape === 'ellipse') return s.rx > 0 && s.ry > 0;
    const [a, b, c] = s.points;
    return Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) > 1e-9;
  }

  // ------------------------------------------------------------ drawing
  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(e);
    return e;
  }
  function drawShape(s, attrs, parent) {
    const base = { fill: FILL[s.color], ...attrs };
    if (s.shape === 'rect') return el('rect', { x: s.x, y: Y(s.y + s.h), width: s.w, height: s.h, ...base }, parent);
    if (s.shape === 'ellipse') return el('ellipse', { cx: s.cx, cy: Y(s.cy), rx: s.rx, ry: s.ry, ...base }, parent);
    return el('polygon', { points: s.points.map(p => `${p[0]},${Y(p[1])}`).join(' '), ...base }, parent);
  }
  function render() {
    svg.textContent = '';
    svg.classList.toggle('select', tool === 'select');
    el('rect', { x: 0, y: 0, width: 10, height: 10, fill: '#f6f2e8' });
    shapes.forEach((s) => drawShape(s, {}));
    if (showGrid) {
      for (let i = 1; i < 10; i++) {
        const o = i === 5 ? 0.32 : 0.16;
        el('line', { x1: i, y1: 0, x2: i, y2: 10, stroke: `rgba(40,40,40,${o})`, 'stroke-width': 0.02 });
        el('line', { x1: 0, y1: i, x2: 10, y2: i, stroke: `rgba(40,40,40,${o})`, 'stroke-width': 0.02 });
      }
    }
    el('rect', { x: 0, y: 0, width: 10, height: 10, fill: 'none', stroke: '#5a564f', 'stroke-width': 0.04 });
    for (let i = 0; i <= 10; i++) {
      el('text', { x: i, y: 10.45, 'font-size': 0.3, 'text-anchor': 'middle', fill: '#8a8378' }).textContent = i;
      el('text', { x: -0.18, y: Y(i) + 0.1, 'font-size': 0.3, 'text-anchor': 'end', fill: '#8a8378' }).textContent = i;
    }
    if (!shapes.length && !drag && !tri.length) {
      el('text', { x: 5, y: 5, 'font-size': 0.42, 'text-anchor': 'middle', fill: '#a39a8a', 'font-style': 'italic' })
        .textContent = 'Empty: nothing has been placed yet.';
    }
    if (drag && drag.mode === 'draw' && drag.preview) drawShape(drag.preview, { opacity: 0.6, stroke: '#222', 'stroke-width': 0.03, 'stroke-dasharray': '0.1 0.08' });
    if (tri.length) {
      const pts = tri.concat(hover ? [hover] : []);
      if (pts.length >= 2) el('polyline', { points: pts.map(p => `${p[0]},${Y(p[1])}`).join(' '), fill: 'none', stroke: FILL[color], 'stroke-width': 0.06 });
      tri.forEach(p => el('circle', { cx: p[0], cy: Y(p[1]), r: 0.14, fill: FILL[color], stroke: '#fff', 'stroke-width': 0.04 }));
    }
    if (sel >= 0 && shapes[sel]) {
      const s = shapes[sel];
      drawShape(s, { fill: 'none', stroke: '#fff', 'stroke-width': 0.09 });
      drawShape(s, { fill: 'none', stroke: '#111', 'stroke-width': 0.045, 'stroke-dasharray': '0.14 0.1' });
      handles(s).forEach(h => el('rect', { x: h.x - 0.16, y: Y(h.y) - 0.16, width: 0.32, height: 0.32, fill: '#fff', stroke: '#111', 'stroke-width': 0.04 }));
    }
    renderPanel();
    renderLayers();
  }

  function renderLayers() {
    const ul = $('layers');
    ul.textContent = '';
    shapes.forEach((s, i) => {
      const li = document.createElement('li');
      if (i === sel) li.className = 'sel';
      li.innerHTML = `<span class="dot" style="background:${FILL[s.color]}"></span><span class="txt">${i + 1}. ${describe(s)}</span>`;
      li.onclick = () => { sel = i; render(); };
      ul.appendChild(li);
    });
    if (!shapes.length) ul.innerHTML = '<li class="muted">none yet</li>';
  }

  const FIELDS = { rect: ['x', 'y', 'w', 'h'], ellipse: ['cx', 'cy', 'rx', 'ry'] };
  const LABELS = { x: 'x (left)', y: 'y (bottom)', w: 'width', h: 'height', cx: 'centre x', cy: 'centre y', rx: 'half-width', ry: 'half-height' };
  function renderPanel() {
    const f = $('fields');
    if (sel < 0 || !shapes[sel]) {
      f.className = 'muted small';
      f.textContent = 'Nothing selected. Draw a shape, or pick one in the list below.';
      return;
    }
    if (f.contains(document.activeElement)) return;  // don't rebuild under the cursor
    const s = shapes[sel];
    f.className = 'fields';
    f.textContent = '';
    const add = (label, input) => { const l = document.createElement('label'); l.textContent = label; f.append(l, input); };
    const cs = document.createElement('select');
    Object.keys(FILL).forEach(c => { const o = document.createElement('option'); o.value = o.textContent = c; if (c === s.color) o.selected = true; cs.append(o); });
    cs.onchange = () => change({ ...shapes[sel], color: cs.value });
    add('colour', cs);
    const num = (label, get, set) => {
      const i = document.createElement('input');
      i.type = 'text'; i.inputMode = 'decimal'; i.value = fmt(get());
      i.onchange = () => {
        const v = parseFloat(i.value.replace(',', '.'));
        if (isNaN(v)) { i.value = fmt(get()); return; }
        const next = set(q8(v));
        if (valid(next)) change(next); else { status('That would leave the board or make the shape vanish.'); i.value = fmt(get()); }
      };
      add(label, i);
    };
    if (s.shape === 'triangle') {
      s.points.forEach((p, k) => {
        num(`corner ${k + 1} x`, () => shapes[sel].points[k][0], v => ({ ...shapes[sel], points: shapes[sel].points.map((q, j) => j === k ? [v, q[1]] : q) }));
        num(`corner ${k + 1} y`, () => shapes[sel].points[k][1], v => ({ ...shapes[sel], points: shapes[sel].points.map((q, j) => j === k ? [q[0], v] : q) }));
      });
    } else {
      FIELDS[s.shape].forEach(k => num(LABELS[k], () => shapes[sel][k], v => ({ ...shapes[sel], [k]: v })));
    }
  }

  // ------------------------------------------------------------ changes and saving
  function remember() { history.push(JSON.stringify(shapes)); if (history.length > 200) history.shift(); }
  function change(s) { remember(); shapes[sel] = s; render(); save(); }
  function status(t) { $('status').textContent = t; }
  function save() {
    clearTimeout(saveTimer);
    status('saving…');
    saveTimer = setTimeout(saveNow, 250);
  }
  function saveNow() {
    clearTimeout(saveTimer);
    saveTimer = null;
    const body = JSON.stringify(shapes);
    saving = saving.then(() => fetch(`/api/builds/${BID}/shapes`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body, credentials: 'same-origin' })
      .then(r => r.json().then(d => {
        if (!r.ok) { status('Not saved: ' + (d.error || r.status)); return; }
        status(`saved · ${d.count} shape${d.count === 1 ? '' : 's'}`);
      }))
      .catch(() => status('Not saved: the server could not be reached. Your next change will try again.')));
    return saving;
  }
  window.twoRoomsFlush = () => (saveTimer ? saveNow() : saving);

  function pt(evt) {
    const p = svg.createSVGPoint();
    p.x = evt.clientX; p.y = evt.clientY;
    const m = p.matrixTransform(svg.getScreenCTM().inverse());
    return [m.x, 10 - m.y];
  }
  function topAt(x, y) {
    for (let i = shapes.length - 1; i >= 0; i--) if (inside(shapes[i], x, y)) return i;
    return -1;
  }
  function handleAt(x, y) {
    if (sel < 0) return null;
    const r = 0.3;
    return handles(shapes[sel]).find(h => Math.abs(h.x - x) < r && Math.abs(h.y - y) < r) || null;
  }

  svg.addEventListener('pointerdown', (evt) => {
    if (evt.button !== undefined && evt.button !== 0) return;
    const [rx, ry] = pt(evt);
    const x = snap(rx), y = snap(ry);
    const h = handleAt(rx, ry);
    if (h) {
      drag = { mode: 'resize', h, orig: JSON.parse(JSON.stringify(shapes[sel])), before: JSON.stringify(shapes) };
    } else if (tool === 'select') {
      const i = topAt(rx, ry);
      sel = i;
      if (i >= 0) drag = { mode: 'move', x0: rx, y0: ry, orig: JSON.parse(JSON.stringify(shapes[i])), before: JSON.stringify(shapes) };
    } else if (tool === 'triangle') {
      if (shapes.length >= MAX) { status(`A build holds at most ${MAX} shapes.`); return; }
      tri.push([x, y]);
      if (tri.length === 3) {
        const t = { shape: 'triangle', color, points: tri };
        tri = [];
        if (valid(t)) { remember(); shapes.push(t); sel = shapes.length - 1; save(); }
        else status('Those three corners are on one line; try again.');
      }
    } else {
      if (shapes.length >= MAX) { status(`A build holds at most ${MAX} shapes.`); return; }
      drag = { mode: 'draw', x0: x, y0: y, preview: null };
    }
    svg.setPointerCapture(evt.pointerId);
    render();
    evt.preventDefault();
  });

  svg.addEventListener('pointermove', (evt) => {
    const [rx, ry] = pt(evt);
    const x = snap(rx), y = snap(ry);
    if (tri.length) { hover = [x, y]; render(); }
    if (!drag) return;
    if (drag.mode === 'draw') {
      drag.preview = fromBox(tool, color, drag.x0, drag.y0, x, y);
    } else if (drag.mode === 'move') {
      const dx = snapOn ? Math.round((rx - drag.x0) / STEP) * STEP : q8(rx - drag.x0);
      const dy = snapOn ? Math.round((ry - drag.y0) / STEP) * STEP : q8(ry - drag.y0);
      shapes[sel] = clampInside(shifted(drag.orig, dx, dy));
    } else if (drag.mode === 'resize') {
      const o = drag.orig, h = drag.h;
      if (o.shape === 'triangle') {
        const t = { ...o, points: o.points.map((p, i) => i === h.id ? [x, y] : p) };
        if (valid(t)) shapes[sel] = t;
      } else {
        const [x0, y0, x1, y1] = bbox(o);
        const fx = h.id.includes('l') ? x1 : x0, fy = h.id.includes('b') ? y1 : y0;
        const n = fromBox(o.shape, o.color, fx, fy, x, y);
        if (valid(n)) shapes[sel] = n;
      }
    }
    render();
  });

  function finish() {
    if (!drag) return;
    if (drag.mode === 'draw') {
      const p = drag.preview;
      if (p && valid(p)) { remember(); shapes.push(p); sel = shapes.length - 1; save(); }
      else if (!p || !valid(p)) status(tool === 'rect' ? 'Drag across the board to draw a rectangle.' : 'Drag across the board to draw an ellipse.');
    } else if (JSON.stringify(shapes) !== drag.before) {
      history.push(drag.before);
      save();
    }
    drag = null;
    render();
  }
  svg.addEventListener('pointerup', finish);
  svg.addEventListener('pointercancel', () => { if (drag && drag.before) shapes = JSON.parse(drag.before); drag = null; render(); });
  svg.addEventListener('pointerleave', () => { hover = null; if (tri.length) render(); });

  // ------------------------------------------------------------ controls
  root.querySelectorAll('[data-tool]').forEach(b => b.addEventListener('click', () => {
    tool = b.dataset.tool; tri = [];
    root.querySelectorAll('[data-tool]').forEach(x => x.classList.toggle('on', x === b));
    $('hint').textContent = {
      rect: 'Drag on the board to draw a rectangle.', ellipse: 'Drag on the board to draw an ellipse (drag across the box it fits in).',
      triangle: 'Click three corners.', select: 'Click a shape to select it; drag it to move; drag a white handle to resize.',
    }[tool];
    render();
  }));
  root.querySelectorAll('[data-color]').forEach(b => b.addEventListener('click', () => {
    color = b.dataset.color;
    root.querySelectorAll('[data-color]').forEach(x => x.classList.toggle('on', x === b));
    if (sel >= 0 && tool === 'select') change({ ...shapes[sel], color });
    render();
  }));
  $('undo').onclick = undo;
  $('clear').onclick = () => { if (!shapes.length) return; remember(); shapes = []; sel = -1; render(); save(); };
  $('del').onclick = del;
  $('up').onclick = () => reorder(1);
  $('down').onclick = () => reorder(-1);
  $('snap').onchange = (e) => { snapOn = e.target.checked; };
  $('gridtoggle').onchange = (e) => { showGrid = e.target.checked; render(); };

  function undo() {
    if (!history.length) { status('Nothing to undo.'); return; }
    shapes = JSON.parse(history.pop()); sel = Math.min(sel, shapes.length - 1); render(); save();
  }
  function del() {
    if (sel < 0) return;
    remember(); shapes.splice(sel, 1); sel = -1; render(); save();
  }
  function reorder(d) {
    const j = sel + d;
    if (sel < 0 || j < 0 || j >= shapes.length) return;
    remember(); [shapes[sel], shapes[j]] = [shapes[j], shapes[sel]]; sel = j; render(); save();
  }
  document.addEventListener('keydown', (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); undo(); return; }
    if (typing) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && sel >= 0) { e.preventDefault(); del(); }
    else if (e.key === 'Escape') { tri = []; sel = -1; render(); }
    else if (sel >= 0 && e.key.startsWith('Arrow')) {
      e.preventDefault();
      const st = snapOn ? STEP : 0.125;
      const d = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, st], ArrowDown: [0, -st] }[e.key];
      const n = shifted(shapes[sel], d[0], d[1]);
      if (valid(n)) change(n);
    }
  });

  // flush the last change before a submit form leaves the page
  document.querySelectorAll('form[data-flush], #submitbtn').forEach(x => {
    const form = x.tagName === 'FORM' ? x : x.form;
    if (!form || form.dataset.flushBound) return;
    form.dataset.flushBound = '1';
    form.addEventListener('submit', (e) => {
      if (form.dataset.flushed) return;
      e.preventDefault();
      status('saving before submitting…');
      Promise.resolve(window.twoRoomsFlush()).then(() => { form.dataset.flushed = '1'; form.submit(); });
    });
  });

  status(shapes.length ? `saved · ${shapes.length} shape${shapes.length === 1 ? '' : 's'}` : 'Nothing placed yet.');
  render();
})();
