"""Static, dependency-free operator UI served by the loopback listener."""

# Embedded CSS and JavaScript retain readable source lines rather than Python wrapping.
# ruff: noqa: E501

from __future__ import annotations


def render_index() -> str:
    return _INDEX_HTML


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AQELYN</title>
  <link rel="stylesheet" href="/assets/app.css">
</head>
<body>
  <header class="topbar">
    <div>
      <strong class="brand">AQELYN</strong>
      <span class="product">Operator surface</span>
    </div>
    <div class="runtime-meta" id="runtime-meta">Connecting</div>
  </header>
  <main>
    <nav class="tabs" aria-label="Views">
      <button class="tab active" data-view="health" type="button">Health</button>
      <button class="tab" data-view="findings" type="button">Findings</button>
      <button class="tab" data-view="inventory" type="button">Inventory</button>
      <button class="tab" data-view="vulnerabilities" type="button">Vulnerabilities</button>
      <button class="tab" data-view="ispm" type="button">Identity posture</button>
      <button class="tab" data-view="exposure" type="button">Exposure</button>
      <button class="tab" data-view="secrets" type="button">Secrets</button>
      <button class="tab" data-view="supplychain" type="button">Supply chain</button>
    </nav>
    <section class="tenant-bar" id="tenant-bar" hidden>
      <label for="tenant-id">Tenant ID</label>
      <input id="tenant-id" name="tenant_id" autocomplete="off" spellcheck="false">
      <button id="apply-tenant" type="button">Apply</button>
    </section>
    <section class="status-band" aria-live="polite">
      <span id="view-title">Health</span>
      <span id="view-status">Loading</span>
      <button id="refresh" type="button">Refresh</button>
    </section>
    <section id="notice" class="notice" hidden></section>
    <section class="data-region" aria-live="polite">
      <table>
        <thead id="data-head"></thead>
        <tbody id="data-body"></tbody>
      </table>
      <div id="empty" class="empty" hidden>No records</div>
    </section>
    <footer class="pager">
      <button id="previous" type="button" disabled>Previous</button>
      <span id="page-label">Page 1</span>
      <button id="next" type="button" disabled>Next</button>
    </footer>
  </main>
  <script src="/assets/app.js" defer></script>
</body>
</html>
"""

APP_CSS = """
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #17211b;
  background: #f4f6f3;
  letter-spacing: 0;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; min-width: 320px; background: #f4f6f3; }
button, input { font: inherit; letter-spacing: 0; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .45; }
.topbar {
  min-height: 64px; padding: 12px 24px; display: flex; align-items: center;
  justify-content: space-between; gap: 20px; color: #fff; background: #17211b;
  border-bottom: 4px solid #e4b63d;
}
.brand { display: block; font-size: 20px; }
.product, .runtime-meta { color: #d6dfd9; font-size: 13px; }
main { width: min(1180px, 100%); margin: 0 auto; padding: 20px 24px 36px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid #cbd3ce; }
.tab {
  min-height: 42px; padding: 0 14px; border: 0; border-bottom: 3px solid transparent;
  color: #43524a; background: transparent;
}
.tab.active { color: #17211b; border-bottom-color: #247d57; font-weight: 700; }
.tenant-bar, .status-band, .pager {
  display: flex; align-items: center; gap: 10px; min-height: 52px;
}
.tenant-bar { padding: 12px 0; border-bottom: 1px solid #dbe1dd; }
.tenant-bar input { min-width: min(420px, 65vw); padding: 8px 10px; border: 1px solid #9eaaa3; border-radius: 4px; }
.tenant-bar button, .status-band button, .pager button {
  min-height: 34px; padding: 6px 12px; border: 1px solid #829088; border-radius: 4px;
  color: #17211b; background: #fff;
}
.status-band { justify-content: space-between; padding: 10px 0; }
#view-title { font-size: 18px; font-weight: 700; }
#view-status { margin-left: auto; color: #526158; font-size: 13px; }
.notice { margin: 0 0 12px; padding: 10px 12px; border-left: 4px solid #c28a16; background: #fff7df; }
.notice.error { border-left-color: #b8413c; background: #fff0ef; }
.data-region { overflow-x: auto; border: 1px solid #cbd3ce; background: #fff; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { padding: 10px 12px; text-align: left; vertical-align: top; border-bottom: 1px solid #e3e8e5; overflow-wrap: anywhere; }
th { color: #43524a; background: #edf1ee; font-size: 12px; text-transform: uppercase; }
td { font-size: 14px; }
.state { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 12px; font-weight: 700; }
.state.healthy, .state.low { color: #155d40; background: #dff3e8; }
.state.degraded, .state.medium { color: #795500; background: #fff0c4; }
.state.unavailable, .state.high, .state.immediate { color: #8a2d29; background: #fde3e1; }
.detail { color: #526158; font-size: 12px; white-space: pre-wrap; }
.empty { padding: 28px; text-align: center; color: #65736b; }
.pager { justify-content: flex-end; }
#page-label { min-width: 70px; text-align: center; font-size: 13px; }
@media (max-width: 680px) {
  .topbar { align-items: flex-start; padding: 12px 16px; }
  main { padding: 14px 12px 28px; }
  .tabs { overflow-x: auto; }
  .tenant-bar { align-items: stretch; flex-direction: column; }
  .tenant-bar input { width: 100%; min-width: 0; }
  th, td { padding: 8px; }
}
"""

APP_JS = r"""
"use strict";

const state = { view: "health", meta: null, cursor: null, history: [], page: 1 };
const $ = (id) => document.getElementById(id);

function tenantQuery() {
  if (!state.meta || state.meta.tenant_mode !== "enterprise") return "";
  const value = $("tenant-id").value.trim();
  return value ? `tenant_id=${encodeURIComponent(value)}` : "";
}

function setNotice(message, error = false) {
  const box = $("notice");
  box.hidden = !message;
  box.textContent = message || "";
  box.classList.toggle("error", error);
}

function cell(row, value, className = "") {
  const td = document.createElement("td");
  td.textContent = value == null ? "Unknown" : String(value);
  if (className) td.className = className;
  row.appendChild(td);
}

function badge(row, value) {
  const td = document.createElement("td");
  const span = document.createElement("span");
  span.className = `state ${String(value || "unknown").toLowerCase()}`;
  span.textContent = value || "Unknown";
  td.appendChild(span);
  row.appendChild(td);
}

function headings(values) {
  const row = document.createElement("tr");
  values.forEach((value) => {
    const th = document.createElement("th");
    th.textContent = value;
    row.appendChild(th);
  });
  $("data-head").replaceChildren(row);
}

function renderHealth(payload) {
  headings(["Service", "Status", "Ready", "Detail"]);
  const rows = Object.entries(payload.services).sort(([a], [b]) => a.localeCompare(b));
  const body = document.createDocumentFragment();
  rows.forEach(([name, item]) => {
    const row = document.createElement("tr");
    cell(row, name);
    badge(row, item.status);
    cell(row, item.ready ? "Yes" : "No");
    cell(row, item.detail || "", "detail");
    body.appendChild(row);
  });
  $("data-body").replaceChildren(body);
  $("empty").hidden = rows.length !== 0;
  $("view-status").textContent = `${rows.length} services / ${payload.phase}`;
  pager(null);
}

function unknownSummary(factors) {
  if (!factors || typeof factors !== "object") return "";
  return Object.entries(factors)
    .filter(([, value]) => value && value.status === "unknown")
    .map(([name, value]) => `${name}: ${value.reason || "unknown"}`)
    .join("\n");
}

function explainSummary(explain) {
  if (explain == null) return "Explanation unavailable";
  const preferred = ["statement", "reason", "confidence", "lifecycle", "conflicts"];
  const parts = preferred
    .filter((name) => Object.prototype.hasOwnProperty.call(explain, name))
    .map((name) => {
      const value = explain[name];
      if (typeof value === "object") return `${name}: ${JSON.stringify(value)}`;
      return `${name}: ${value}`;
    });
  return parts.length ? parts.join("\n") : "Owner derivation available";
}

function renderDomain(payload) {
  const body = document.createDocumentFragment();
  const headingSets = {
    ispm: ["Subject", "Posture", "Confidence", "Derivation"],
    exposure: ["Asset", "Reachability", "Score", "Derivation"],
    secrets: ["Asset", "Kind", "Confidence", "Derivation"],
    supplychain: ["Component", "Version", "Provenance", "Derivation"],
  };
  headings(headingSets[state.view]);
  payload.items.forEach((item) => {
    const record = item.record;
    const row = document.createElement("tr");
    if (state.view === "ispm") {
      cell(row, record.subject_ref);
      cell(row, Number(record.score).toFixed(1));
      cell(row, Number(record.confidence).toFixed(2));
    } else if (state.view === "exposure") {
      cell(row, record.asset_ref?.ref_id || record.id);
      badge(row, record.reachability);
      cell(row, record.score == null ? "Unknown" : Number(record.score).toFixed(1));
    } else if (state.view === "secrets") {
      cell(row, record.id);
      cell(row, item.explain?.asset_kind || record.classification || record.kind || "Unknown");
      cell(row, Number(record.claim_confidence).toFixed(2));
    } else {
      cell(row, record.name);
      cell(row, record.version);
      badge(row, record.provenance_status);
    }
    cell(row, explainSummary(item.explain), "detail");
    body.appendChild(row);
  });
  $("data-body").replaceChildren(body);
  $("empty").hidden = payload.items.length !== 0;
  $("view-status").textContent = `${payload.returned} returned`;
  const reasons = (payload.degradation_reasons || []).join(" / ");
  setNotice(reasons || (payload.degraded ? "This read is degraded and may be incomplete." : ""));
  pager(payload.next_cursor);
}

function renderCollection(payload) {
  if (["ispm", "exposure", "secrets", "supplychain"].includes(state.view)) {
    renderDomain(payload);
    return;
  }
  const body = document.createDocumentFragment();
  if (state.view === "findings") {
    headings(["Finding", "Severity", "Status", "Why it matters"]);
    payload.items.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, item.title);
      badge(row, item.severity);
      cell(row, item.status);
      cell(row, item.why_it_matters, "detail");
      body.appendChild(row);
    });
  } else if (state.view === "inventory") {
    headings(["Asset", "State"]);
    payload.items.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, item.asset_id);
      badge(row, payload.inventory.degraded ? "degraded" : "healthy");
      body.appendChild(row);
    });
    const warning = payload.inventory.degraded ? "Inventory is degraded; this is not a complete estate." : "";
    setNotice(warning);
  } else {
    headings(["Vulnerability", "Priority", "Score", "Unknown factors"]);
    payload.items.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, item.vulnerability_id);
      badge(row, item.priority);
      cell(row, Number(item.score).toFixed(1));
      cell(row, unknownSummary(item.factors), "detail");
      body.appendChild(row);
    });
    const reasons = payload.assessment.unavailable.map((item) => item.reason).join(" / ");
    setNotice(reasons || (payload.assessment.degraded ? "Assessment is degraded." : ""));
  }
  $("data-body").replaceChildren(body);
  $("empty").hidden = payload.items.length !== 0;
  $("view-status").textContent = payload.total == null ? `${payload.returned} returned` : `${payload.returned} of ${payload.total}`;
  pager(payload.next_cursor);
}

function pager(nextCursor) {
  $("previous").disabled = state.history.length === 0;
  $("next").disabled = !nextCursor;
  $("next").dataset.cursor = nextCursor || "";
  $("page-label").textContent = `Page ${state.page}`;
}

async function request(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || `Request failed (${response.status})`);
  return payload;
}

async function load() {
  setNotice("");
  $("view-status").textContent = "Loading";
  try {
    if (state.view === "health") {
      renderHealth(await request("/health"));
      return;
    }
    const tenant = tenantQuery();
    if (state.meta.tenant_mode === "enterprise" && !tenant) {
      throw new Error("Tenant ID is required in enterprise mode.");
    }
    const params = new URLSearchParams(tenant);
    params.set("limit", "50");
    if (state.cursor) params.set("cursor", state.cursor);
    const paths = {
      findings: "/api/v1/findings",
      inventory: "/api/v1/inventory",
      vulnerabilities: "/api/v1/vulnerabilities",
      ispm: "/api/v1/ispm",
      exposure: "/api/v1/exposure",
      secrets: "/api/v1/secrets",
      supplychain: "/api/v1/supplychain",
    };
    const path = paths[state.view];
    renderCollection(await request(`${path}?${params.toString()}`));
  } catch (error) {
    $("data-head").replaceChildren();
    $("data-body").replaceChildren();
    $("empty").hidden = false;
    $("view-status").textContent = "Unavailable";
    setNotice(error.message, true);
    pager(null);
  }
}

function selectView(view) {
  state.view = view;
  state.cursor = null;
  state.history = [];
  state.page = 1;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  const titles = {
    health: "Health",
    findings: "Findings",
    inventory: "Inventory",
    vulnerabilities: "Vulnerabilities",
    ispm: "Identity posture",
    exposure: "Exposure",
    secrets: "Secrets",
    supplychain: "Supply chain",
  };
  $("view-title").textContent = titles[view];
  load();
}

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
$("refresh").addEventListener("click", load);
$("apply-tenant").addEventListener("click", () => selectView(state.view));
$("next").addEventListener("click", () => {
  state.history.push(state.cursor);
  state.cursor = $("next").dataset.cursor;
  state.page += 1;
  load();
});
$("previous").addEventListener("click", () => {
  state.cursor = state.history.pop() || null;
  state.page = Math.max(1, state.page - 1);
  load();
});

(async () => {
  try {
    state.meta = await request("/api/v1/meta");
    $("runtime-meta").textContent = `${state.meta.backend} / ${state.meta.tenant_mode} / local operator`;
    $("tenant-bar").hidden = state.meta.tenant_mode !== "enterprise";
    await load();
  } catch (error) {
    setNotice(error.message, true);
  }
})();
"""
