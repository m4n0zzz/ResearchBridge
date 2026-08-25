const TYPES = {
  DOCUMENT: { label: "Documents", color: "#165c46" },
  RESEARCHER: { label: "Researchers", color: "#dd6b43" },
  DEPARTMENT: { label: "Departments", color: "#8668b5" },
  TOPIC: { label: "Topics", color: "#d1a319" },
  METHOD: { label: "Methods", color: "#3475b9" },
  DATASET: { label: "Datasets", color: "#19a083" },
  SOFTWARE: { label: "Software", color: "#d14e71" },
  PUBLICATION: { label: "Publications", color: "#687770" },
};

const state = { data: { nodes: [], edges: [], insights: [], documents: [] }, activeTypes: new Set(Object.keys(TYPES)), files: [], previousFocus: null };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const pct = (value) => `${Math.round(Number(value) * 100)}%`;

function setupFilters() {
  const container = $("#filters");
  for (const [type, meta] of Object.entries(TYPES)) {
    const label = document.createElement("label");
    label.className = "filter";
    label.style.setProperty("--dot", meta.color);
    label.innerHTML = `<input type="checkbox" value="${type}" checked><span class="type-dot"></span><span>${meta.label}</span>`;
    label.querySelector("input").addEventListener("change", event => {
      event.target.checked ? state.activeTypes.add(type) : state.activeTypes.delete(type);
      renderGraph();
    });
    container.append(label);
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload;
  try { payload = await response.json(); } catch { payload = { detail: "The server returned an unreadable response." }; }
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    $("#status-dot").classList.add("ready");
    $("#system-status").textContent = data.ai_configured ? `Gemini ready · ${data.ai_model}` : "Local demo ready · Gemini key not set";
  } catch {
    $("#system-status").textContent = "Server unavailable";
  }
}

async function refreshGraph() {
  state.data = await api("/api/graph");
  renderStats();
  renderGraph();
  renderInsights();
}

function renderStats() {
  const values = [
    [state.data.documents.length, "artifacts"], [state.data.nodes.length, "nodes"],
    [state.data.edges.length, "links"], [state.data.insights.length, "insights"],
  ];
  $("#stats").innerHTML = values.map(([value, label]) => `<span class="stat"><strong>${value}</strong>${label}</span>`).join("");
}

function layoutNodes(nodes, edges, width, height) {
  const centerX = width / 2, centerY = height / 2;
  const positions = new Map();
  nodes.forEach((node, index) => {
    const angle = index * 2.399963;
    const radiusBase = node.type === "TOPIC" ? 45 : node.type === "DOCUMENT" ? 125 : node.type === "RESEARCHER" || node.type === "DEPARTMENT" ? 205 : 170;
    const wobble = (index % 4) * 12;
    positions.set(node.id, { x: centerX + Math.cos(angle) * (radiusBase + wobble), y: centerY + Math.sin(angle) * (radiusBase + wobble), vx: 0, vy: 0 });
  });
  const edgeSet = edges.map(edge => [positions.get(edge.source_entity_id), positions.get(edge.target_entity_id)]).filter(pair => pair[0] && pair[1]);
  for (let iteration = 0; iteration < 90; iteration += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      const a = positions.get(nodes[i].id);
      a.vx += (centerX - a.x) * 0.0007; a.vy += (centerY - a.y) * 0.0007;
      for (let j = i + 1; j < nodes.length; j += 1) {
        const b = positions.get(nodes[j].id); let dx = b.x - a.x, dy = b.y - a.y;
        const d2 = Math.max(100, dx * dx + dy * dy); const force = 190 / d2;
        a.vx -= dx * force; a.vy -= dy * force; b.vx += dx * force; b.vy += dy * force;
      }
    }
    for (const [a, b] of edgeSet) {
      const dx = b.x - a.x, dy = b.y - a.y, distance = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (distance - 105) * 0.0017;
      a.vx += dx * force; a.vy += dy * force; b.vx -= dx * force; b.vy -= dy * force;
    }
    for (const point of positions.values()) {
      point.vx *= .83; point.vy *= .83; point.x = Math.max(38, Math.min(width - 38, point.x + point.vx)); point.y = Math.max(35, Math.min(height - 55, point.y + point.vy));
    }
  }
  return positions;
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function renderGraph() {
  const hasNodes = state.data.nodes.length > 0;
  $("#empty-state").hidden = hasNodes;
  $("#graph-wrap").hidden = !hasNodes;
  if (!hasNodes) return;
  const svg = $("#graph"); svg.replaceChildren();
  const width = Math.max(360, svg.clientWidth || 900), height = Math.max(440, svg.clientHeight || 520);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const nodes = state.data.nodes.filter(node => state.activeTypes.has(node.type));
  const ids = new Set(nodes.map(node => node.id));
  const edges = state.data.edges.filter(edge => ids.has(edge.source_entity_id) && ids.has(edge.target_entity_id));
  const positions = layoutNodes(nodes, edges, width, height);
  const nodeById = new Map(nodes.map(node => [node.id, node]));
  const edgeLayer = svgElement("g"), nodeLayer = svgElement("g"); svg.append(edgeLayer, nodeLayer);
  edges.forEach(edge => {
    const source = positions.get(edge.source_entity_id), target = positions.get(edge.target_entity_id);
    const sourceName = nodeById.get(edge.source_entity_id)?.display_name || "source";
    const targetName = nodeById.get(edge.target_entity_id)?.display_name || "target";
    const line = svgElement("line", { x1: source.x, y1: source.y, x2: target.x, y2: target.y, class: "graph-edge", tabindex: "0", role: "button", "aria-label": `${sourceName} to ${targetName}: ${edge.relationship_type}, ${pct(edge.confidence)} confidence` });
    line.addEventListener("click", () => openDetails("edge", edge.id));
    line.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDetails("edge", edge.id); } });
    edgeLayer.append(line);
  });
  nodes.forEach(node => {
    const point = positions.get(node.id), group = svgElement("g", { class: "graph-node", transform: `translate(${point.x} ${point.y})`, tabindex: "0", role: "button", "aria-label": `${node.type}: ${node.display_name}` });
    group.style.setProperty("--node", TYPES[node.type]?.color || "#687770");
    const radius = node.type === "TOPIC" ? 14 : node.type === "DOCUMENT" ? 12 : 9;
    group.append(svgElement("circle", { r: radius }));
    const text = svgElement("text", { y: radius + 14 });
    const label = node.display_name.length > 25 ? `${node.display_name.slice(0, 23)}…` : node.display_name;
    text.textContent = label; group.append(text);
    group.addEventListener("click", () => openDetails("node", node.id));
    group.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDetails("node", node.id); } });
    nodeLayer.append(group);
  });
  $("#legend").innerHTML = Object.entries(TYPES).filter(([type]) => state.activeTypes.has(type)).map(([, meta]) => `<span><i class="type-dot" style="--dot:${meta.color}"></i>${meta.label}</span>`).join("");
}

function renderInsights() {
  const groups = {
    COLLABORATION_OPPORTUNITY: $("#collaboration-list"),
    POTENTIAL_OVERLAP: $("#overlap-list"),
  };
  for (const [type, container] of Object.entries(groups)) {
    const insights = state.data.insights.filter(item => item.insight_type === type);
    if (!insights.length) { container.innerHTML = `<p class="muted">${type === "POTENTIAL_OVERLAP" ? "No review signals yet." : "No opportunities yet."}</p>`; continue; }
    container.replaceChildren(...insights.map(item => {
      const button = document.createElement("button"); button.className = "insight-card";
      button.innerHTML = `<span class="score">${pct(item.score)} match</span><strong>${escapeHtml(item.source_title)} ↔ ${escapeHtml(item.target_title)}</strong><p>${escapeHtml(item.explanation)}</p>`;
      button.addEventListener("click", () => openDetails("insight", item.id));
      return button;
    }));
  }
}

async function openDetails(kind, id) {
  try {
    state.previousFocus = document.activeElement;
    const data = await api(`/api/details/${kind}/${id}`), item = data.item;
    const title = kind === "node" ? item.display_name : kind === "edge" ? `${item.source_name} → ${item.target_name}` : `${item.source_title} ↔ ${item.target_title}`;
    $("#drawer-type").textContent = kind === "insight" ? item.insight_type.replaceAll("_", " ") : kind === "edge" ? "Relationship evidence" : item.type;
    $("#drawer-title").textContent = title;
    let html = "";
    if (kind === "node") html += `<div class="detail-meta"><span class="pill">${escapeHtml(item.type)}</span><span class="pill">${pct(item.confidence)} confidence</span></div><p>${escapeHtml(item.description)}</p>`;
    if (kind === "edge") html += `<div class="detail-meta"><span class="pill">${escapeHtml(item.relationship_type)}</span><span class="pill">${pct(item.confidence)} confidence</span><span class="pill">${item.derived ? "Derived" : "Extracted"}</span></div><p>${escapeHtml(item.explanation)}</p>`;
    if (kind === "insight") {
      html += `<div class="detail-meta"><span class="pill">${pct(item.score)} score</span><span class="pill">Deterministic insight</span></div><p class="why">${escapeHtml(item.explanation)}</p>`;
      for (const [label, value] of Object.entries(item.evidence || {})) html += `<div class="evidence-block"><strong>${escapeHtml(label.replaceAll("_", " "))}</strong><p>${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</p></div>`;
    } else if (data.evidence.length) {
      html += `<h3>Source provenance</h3>` + data.evidence.map(evidence => `<div class="evidence-block"><small>${escapeHtml(evidence.document_title)} · ${escapeHtml(evidence.location)}</small><blockquote>“${escapeHtml(evidence.excerpt)}”</blockquote></div>`).join("");
    } else html += `<p class="muted">This derived connection is explained by its deterministic score; inspect the linked insight for supporting features.</p>`;
    $("#drawer-content").innerHTML = html;
    $("#drawer-backdrop").hidden = false;
    $("#detail-drawer").inert = false; $("#detail-drawer").classList.add("open"); $("#detail-drawer").setAttribute("aria-hidden", "false");
    document.querySelector("main").inert = true; $(".topbar").inert = true; $("#drawer-close").focus();
  } catch (error) { showStatus(error.message, true); }
}

function closeDrawer() {
  $("#detail-drawer").classList.remove("open"); $("#detail-drawer").setAttribute("aria-hidden", "true"); $("#detail-drawer").inert = true;
  document.querySelector("main").inert = false; $(".topbar").inert = false; $("#drawer-backdrop").hidden = true;
  if (state.previousFocus?.focus) state.previousFocus.focus();
}

function showStatus(message, error = false) {
  const target = $("#upload-status"); target.textContent = message; target.classList.toggle("error", error);
}

function setFiles(fileList) {
  state.files = [...fileList].slice(0, 8);
  $("#file-list").innerHTML = state.files.map(file => `<div class="file-chip"><strong>${escapeHtml(file.name)}</strong><span>${(file.size / 1024).toFixed(0)} KB</span></div>`).join("");
  $("#ingest-button").disabled = !state.files.length;
}

async function ingestFiles() {
  const button = $("#ingest-button"); button.disabled = true; button.textContent = "Extracting evidence…"; showStatus("Gemini is validating entities, relationships, and evidence.");
  const form = new FormData(); state.files.forEach(file => form.append("files", file));
  try {
    const result = await api("/api/ingest", { method: "POST", body: form });
    const failures = result.results.filter(item => item.status === "error");
    showStatus(failures.length ? failures.map(item => `${item.filename}: ${item.error}`).join(" · ") : `${result.results.length} artifact(s) ingested. Graph refreshed.`, Boolean(failures.length));
    await refreshGraph();
  } catch (error) { showStatus(error.message, true); }
  finally { button.textContent = "Build knowledge graph"; button.disabled = !state.files.length; }
}

async function loadDemo(event) {
  const button = event?.currentTarget; if (button) { button.disabled = true; button.textContent = "Loading synthetic artifacts…"; }
  showStatus("Parsing four synthetic PDF, Markdown, and repository artifacts…");
  try { const result = await api("/api/demo/load", { method: "POST" }); showStatus(`${result.message} ${result.stats.insights} evidence-backed insights found.`); await refreshGraph(); }
  catch (error) { showStatus(error.message, true); }
  finally { if (button) { button.disabled = false; button.textContent = "Load synthetic demo data"; } }
}

async function runQuery() {
  const question = $("#query-input").value.trim(); if (question.length < 3) return;
  const button = $("#query-button"); button.disabled = true; button.textContent = "Retrieving…"; $("#query-result").innerHTML = `<p class="muted">Searching vectors, graph paths, and evidence…</p>`;
  try {
    const result = await api("/api/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
    $("#query-result").innerHTML = `<div class="query-card"><strong>Evidence-backed answer</strong><p>${escapeHtml(result.answer)}</p>${result.caveats.map(item => `<p class="caveat">${escapeHtml(item)}</p>`).join("")}</div>`;
  } catch (error) { $("#query-result").innerHTML = `<p class="assistive error">${escapeHtml(error.message)}</p>`; }
  finally { button.disabled = false; button.textContent = "Search evidence"; }
}

function bindEvents() {
  $("#file-input").addEventListener("change", event => setFiles(event.target.files));
  const dropzone = $("#dropzone");
  ["dragenter", "dragover"].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove("dragover"); }));
  dropzone.addEventListener("drop", event => setFiles(event.dataTransfer.files));
  $("#ingest-button").addEventListener("click", ingestFiles);
  $("#demo-button").addEventListener("click", loadDemo);
  document.querySelectorAll(".demo-trigger").forEach(button => button.addEventListener("click", loadDemo));
  $("#query-button").addEventListener("click", runQuery);
  $("#query-input").addEventListener("keydown", event => { if (event.key === "Enter") runQuery(); });
  $("#drawer-close").addEventListener("click", closeDrawer); $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", event => {
    const drawer = $("#detail-drawer");
    if (event.key === "Escape" && drawer.classList.contains("open")) closeDrawer();
    if (event.key === "Tab" && drawer.classList.contains("open")) {
      const focusable = [...drawer.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter(item => !item.disabled);
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  let resizeTimer; window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderGraph, 150); });
}

setupFilters(); bindEvents(); checkHealth(); refreshGraph().catch(error => showStatus(error.message, true));
