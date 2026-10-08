// Unifier Database Graph — expandable workflow tree on canvas.
// Click a node to expand its children; drill Company → Project → BP → Record → Fields/Line items → values.
(() => {
  const canvas = document.getElementById("graph");
  const ctx = canvas.getContext("2d");
  const projectSelect = document.getElementById("projectSelect");
  const panel = document.getElementById("panel");
  const panelSub = document.getElementById("panelSub");
  const statsEl = document.getElementById("stats");

  const C = {
    company: "#0a0a0a", projectHub: "#ea580c", hub: "#6b7280", entity: "#e5e7eb",
    bp: "#ffffff", record: "#ffffff", group: "#f4f4f5", lirow: "#fff7ed", field: "#ffffff",
    line: "#9ca3af", ink: "#0a0a0a", accent: "#ea580c", accentInk: "#c2410c",
  };
  const COL = 220, ROW = 30, BOX_W = 188, BOX_H = 24;

  let data = null, root = null;
  let visible = [], edges = [];
  const view = { scale: 1, x: 0, y: 0 };
  let hover = null, selected = null;
  let dragging = false, dragMoved = false, lastX = 0, lastY = 0;
  let uid = 0;

  function node(type, label, sub, expandable, meta) {
    return { id: ++uid, type, label, sub: sub || "", expandable: !!expandable,
             expanded: false, loaded: false, loading: false, children: [], parent: null, meta: meta || {}, x: 0, y: 0 };
  }
  function addKids(parent, kids) { kids.forEach(k => { k.parent = parent; }); parent.children = kids; }

  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = r.width * dpr; canvas.height = r.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    render();
  }
  window.addEventListener("resize", resize);

  async function loadInitial(projectNumber) {
    const url = "/api/db-graph" + (projectNumber ? `?project_number=${encodeURIComponent(projectNumber)}` : "");
    data = await (await fetch(url)).json();
    if (!data.success) return;
    populateSelector();
    buildStats();
    buildRoot();
    relayout();
    fitToView();
    selected = null; renderPanel(null);
    render();
  }
  function populateSelector() {
    if (projectSelect.dataset.filled === "1") { projectSelect.value = data.project.project_number; return; }
    projectSelect.innerHTML = "";
    (data.projects_with_data || []).forEach(p => {
      const o = document.createElement("option");
      o.value = p.project_number;
      o.textContent = `${p.project_number} — ${p.project_name || "(unnamed)"} (${p.records})`;
      projectSelect.appendChild(o);
    });
    projectSelect.value = data.project.project_number;
    projectSelect.dataset.filled = "1";
    projectSelect.addEventListener("change", () => loadInitial(projectSelect.value));
  }

  function buildStats() {
    const c = data.company;
    const btnExp = document.getElementById("btnExportJson");
    if (btnExp) {
      btnExp.href = `/api/project/${encodeURIComponent(data.project.project_number)}/export`;
      btnExp.download = `project_${data.project.project_number}_complete_context.json`;
    }
    statsEl.innerHTML = `
      <div class="stat"><b class="accent">${data.project.project_number}</b>${(data.project.project_name||"").slice(0,20)}</div>
      <div class="stat"><b>${data.project_bp_count}</b>Business Processes</div>
      <div class="stat"><b>${data.project_record_total}</b>Records</div>
      <div class="stat"><b>${c.company_bp_count}</b>Company BPs</div>
      <div class="stat"><b>${c.users}</b>Users</div>`;
  }

  function bpNode(b, scope, project) {
    const n = node("bp", b.bp_name, `${b.records} records`, true,
                   { scope, project: project || "", bp: b.bp_name, records: b.records, info: b });
    return n;
  }

  function buildRoot() {
    const c = data.company;
    root = node("company", c.name, "Company root", true);
    root.loaded = true; root.expanded = true;

    const users = node("entity", "Users", `${c.users}`, false);
    const projects = node("entity", "Projects", `${c.projects_total.toLocaleString()} shells`, false);

    const cHub = node("hub", "Company BPs", `${c.company_bp_count}`, true, {});
    cHub.loaded = true;
    addKids(cHub, (data.company_bps || []).map(b => bpNode(b, "company", "")));

    const pHub = node("projectHub", `Project ${data.project.project_number}`, data.project.project_name, true, {});
    pHub.loaded = true;
    addKids(pHub, (data.project_bps || []).map(b => bpNode(b, "project", data.project.project_number)));

    addKids(root, [users, projects, cHub, pHub]);
  }

  // ---- Tidy horizontal layout: x by depth, y by visible-leaf order ----
  function relayout() {
    visible = []; edges = [];
    let row = 0;
    (function walk(n, depth) {
      n.x = depth * COL;
      const kids = n.expanded ? n.children : [];
      if (!kids.length) { n.y = row * ROW; row++; }
      else {
        kids.forEach(k => walk(k, depth + 1));
        n.y = (kids[0].y + kids[kids.length - 1].y) / 2;
        kids.forEach(k => edges.push({ a: n, b: k }));
      }
      visible.push(n);
    })(root, 0);
  }

  function fitToView() {
    if (!visible.length) return;
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (const n of visible) {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x + BOX_W);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y + BOX_H);
    }
    const r = canvas.parentElement.getBoundingClientRect();
    const sx = r.width / (maxX - minX + 80), sy = r.height / (maxY - minY + 80);
    view.scale = Math.min(1, Math.min(sx, sy));
    view.x = 40 - minX * view.scale;
    view.y = (r.height - (maxY - minY) * view.scale) / 2 - minY * view.scale;
  }
  function S(x, y) { return [x * view.scale + view.x, y * view.scale + view.y]; }
  function rr(x, y, w, h, rad) {
    ctx.beginPath();
    ctx.moveTo(x + rad, y); ctx.arcTo(x + w, y, x + w, y + h, rad);
    ctx.arcTo(x + w, y + h, x, y + h, rad); ctx.arcTo(x, y + h, x, y, rad);
    ctx.arcTo(x, y, x + w, y, rad); ctx.closePath();
  }

  function boxFill(n) {
    if (n === selected) return C.accent;
    return C[n.type] || "#fff";
  }
  function boxText(n) {
    if (n === selected) return "#fff";
    return (n.type === "company" || n.type === "projectHub" || n.type === "hub") ? "#fff" : C.ink;
  }

  function render() {
    const r = canvas.parentElement.getBoundingClientRect();
    ctx.clearRect(0, 0, r.width, r.height);
    const s = view.scale;

    // elbow connectors (parent right-center → child left-center)
    ctx.lineWidth = 1.2;
    for (const e of edges) {
      const [ax, ay] = S(e.a.x + BOX_W, e.a.y + BOX_H / 2);
      const [bx, by] = S(e.b.x, e.b.y + BOX_H / 2);
      const hot = (e.a === hover || e.b === hover || e.a === selected || e.b === selected);
      ctx.strokeStyle = hot ? C.accent : C.line;
      ctx.globalAlpha = hot ? 1 : 0.55;
      const midx = (ax + bx) / 2;
      ctx.beginPath();
      ctx.moveTo(ax, ay); ctx.lineTo(midx, ay); ctx.lineTo(midx, by); ctx.lineTo(bx, by);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    const fs = Math.max(9, 12 * s), fss = Math.max(8, 10 * s);
    for (const n of visible) {
      const [x, y] = S(n.x, n.y);
      const w = BOX_W * s, h = BOX_H * s;
      rr(x, y, w, h, 6 * s);
      ctx.fillStyle = boxFill(n); ctx.fill();
      ctx.lineWidth = (n === hover || n === selected) ? 2 : 1.1;
      ctx.strokeStyle = (n === hover || n === selected) ? C.accentInk : "#000";
      ctx.stroke();
      // type accent tab on the left for BP/record
      if ((n.type === "bp" || n.type === "record") && n !== selected) {
        ctx.fillStyle = C.accent; rr(x, y, 4 * s, h, 2 * s); ctx.fill();
      }
      // label + sub (clipped)
      ctx.save(); rr(x + 6 * s, y, w - 12 * s, h, 4); ctx.clip();
      ctx.fillStyle = boxText(n); ctx.textBaseline = "middle";
      ctx.font = `600 ${fs}px Inter, sans-serif`;
      ctx.fillText(n.label, x + 8 * s, y + (n.sub ? h * 0.36 : h / 2));
      if (n.sub) {
        ctx.font = `400 ${fss}px Inter, sans-serif`;
        ctx.fillStyle = n === selected ? "#ffe" : "#6b7280";
        ctx.fillText(n.sub, x + 8 * s, y + h * 0.72);
      }
      ctx.restore();
      // expand marker
      if (n.expandable) {
        ctx.fillStyle = boxText(n); ctx.font = `700 ${Math.max(11, 13 * s)}px Inter`;
        ctx.textAlign = "center";
        ctx.fillText(n.loading ? "…" : (n.expanded ? "−" : "+"), x + w - 9 * s, y + h / 2);
        ctx.textAlign = "left";
      }
    }
  }

  function pick(mx, my) {
    for (let i = visible.length - 1; i >= 0; i--) {
      const n = visible[i]; const [x, y] = S(n.x, n.y);
      if (mx >= x && mx <= x + BOX_W * view.scale && my >= y && my <= y + BOX_H * view.scale) return n;
    }
    return null;
  }
  // ---- Lazy expansion ----
  async function expandBp(n) {
    const q = `project_number=${encodeURIComponent(n.meta.project || "")}&bp_name=${encodeURIComponent(n.meta.bp)}&scope=${n.meta.scope}`;
    const res = await (await fetch(`/api/db-graph/records?${q}`)).json();
    const recs = (res.records || []).map(rec => node(
      "record", rec.record_no || "(no #)", rec.status || rec.title || "", true,
      { scope: n.meta.scope, project: n.meta.project, bp: n.meta.bp, record_no: rec.record_no }
    ));
    if (!recs.length) { const empty = node("field", "(no records cached)", "", false); addKids(n, [empty]); }
    else addKids(n, recs);
    n.loaded = true;
  }

  async function expandRecord(n) {
    const q = `record_no=${encodeURIComponent(n.meta.record_no)}&bp_name=${encodeURIComponent(n.meta.bp)}&project_number=${encodeURIComponent(n.meta.project || "")}&scope=${n.meta.scope}`;
    const res = await (await fetch(`/api/db-graph/record?${q}`)).json();
    const kids = [];
    const hdr = node("group", "Header fields", `${(res.fields || []).length} cols`, true, {});
    hdr.loaded = true;
    addKids(hdr, (res.fields || []).map(f => node("field", f.k, f.v, false)));
    kids.push(hdr);
    if ((res.line_items || []).length) {
      const li = node("group", "Line items", `${res.line_items.length} rows`, true, {});
      li.loaded = true;
      addKids(li, res.line_items.map((row, i) => {
        const rn = node("lirow", `Line ${i + 1}`, `${Object.keys(row).length} cols`, true, {});
        rn.loaded = true;
        addKids(rn, Object.entries(row).map(([k, v]) => node("field", k, String(v), false)));
        return rn;
      }));
      kids.push(li);
    }
    if (!kids.length) kids.push(node("field", "(no fields)", "", false));
    addKids(n, kids);
    n.loaded = true;
  }

  async function toggle(n) {
    selected = n; renderPanel(n);
    if (!n.expandable) { render(); return; }
    if (n.expanded) { n.expanded = false; relayout(); render(); return; }
    if (!n.loaded) {
      n.loading = true; render();
      try {
        if (n.type === "bp") await expandBp(n);
        else if (n.type === "record") await expandRecord(n);
      } catch (e) { addKids(n, [node("field", "(load error)", String(e).slice(0, 40), false)]); n.loaded = true; }
      n.loading = false;
    }
    n.expanded = true; relayout(); render();
  }

  // ---- Interactions ----
  canvas.addEventListener("mousedown", (e) => { dragging = true; dragMoved = false; lastX = e.offsetX; lastY = e.offsetY; });
  window.addEventListener("mouseup", () => { dragging = false; });
  canvas.addEventListener("mousemove", (e) => {
    if (dragging) {
      const dx = e.offsetX - lastX, dy = e.offsetY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved = true;
      view.x += dx; view.y += dy; lastX = e.offsetX; lastY = e.offsetY; render(); return;
    }
    const n = pick(e.offsetX, e.offsetY);
    if (n !== hover) { hover = n; canvas.style.cursor = n ? "pointer" : "grab"; render(); }
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    view.x = e.offsetX - (e.offsetX - view.x) * f;
    view.y = e.offsetY - (e.offsetY - view.y) * f;
    view.scale = Math.max(0.2, Math.min(3, view.scale * f));
    render();
  }, { passive: false });
  canvas.addEventListener("click", (e) => {
    if (dragMoved) return;
    const n = pick(e.offsetX, e.offsetY);
    if (n) toggle(n);
  });

  // ---- Side panel ----
  function renderPanel(n) {
    [...panel.querySelectorAll(".kv,.sec,.panel-empty")].forEach(el => el.remove());
    if (!n) {
      panel.querySelector("h2").textContent = "Workflow Tree";
      panelSub.textContent = "Company → Project → BP → Record → Fields";
      const p = document.createElement("p"); p.className = "panel-empty";
      p.innerHTML = `Click any node with a <b>+</b> to expand it. Drill all the way down:<br>Project → Business Process → Record → <b>Header fields</b> & <b>Line items</b> → values.`;
      panel.appendChild(p); return;
    }
    const TYPE = { company: "Company", entity: "Entity", hub: "Company BPs", projectHub: "Project",
                   bp: "Business Process", record: "Record", group: "Field group", lirow: "Line item", field: "Field" };
    panel.querySelector("h2").textContent = n.label;
    panelSub.textContent = TYPE[n.type] || n.type;
    const add = (h) => { const d = document.createElement("div"); d.innerHTML = h; while (d.firstChild) panel.appendChild(d.firstChild); };
    if (n.sub) add(`<div class="kv"><span>${n.type === "field" ? "Value" : "Detail"}</span><b>${n.sub}</b></div>`);
    if (n.meta && n.meta.records != null) add(`<div class="kv"><span>Records</span><b>${n.meta.records}</b></div>`);
    if (n.meta && n.meta.bp) add(`<div class="kv"><span>Business Process</span><b>${n.meta.bp}</b></div>`);
    if (n.meta && n.meta.record_no) add(`<div class="kv"><span>Record #</span><b>${n.meta.record_no}</b></div>`);
    if (n.expandable) add(`<div class="sec"><h3>Tip</h3><p class="panel-empty">Click this node on the canvas to ${n.expanded ? "collapse" : "expand"} it.</p></div>`);
  }

  resize();
  loadInitial("");
})();
