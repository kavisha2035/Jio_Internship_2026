/**
 * main.js — OccuSense AI Dashboard (v3 — Workspace Allocation Engine)
 *
 * Handles:
 *  1. WebSocket: receives annotated frames + workspace states
 *  2. Tab 1: live workspace grid (occupied/vacant only, no unknown)
 *  3. Tab 2: analytics — peak hours, DoW, per-workspace utilization table
 *  4. Tab 3: optimization — startup analysis, recommendation cards,
 *             confirm reassignment, generate assignment letter
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let ws               = null;
let wsReconnectTimer = null;
let wsReconnectDelay = 1500;
const WS_MAX_DELAY   = 15000;

let charts           = {};
let analyticsLoaded  = false;
let allStartups      = [];
let currentRec       = null;   // holds last recommendation result

// ─── Tab Switching ─────────────────────────────────────────────────────────────

function switchTab(tabName) {
  document.querySelectorAll('.nav-icon-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

  document.getElementById(`nav-${tabName}`)?.classList.add('active');
  document.getElementById(`panel-${tabName}`)?.classList.add('active');

  if (tabName === 'analytics' && !analyticsLoaded) loadAnalytics();
  if (tabName === 'optimize')                       loadOptimize();
}
window.switchTab = switchTab;

// ─── WebSocket ─────────────────────────────────────────────────────────────────

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url   = `${proto}://${location.host}/ws/live`;
  console.log(`[WS] Connecting to ${url}`);
  ws = new WebSocket(url);

  ws.onopen = () => {
    wsReconnectDelay = 1500;
    setConnectionStatus('live', 'Connected');
    clearTimeout(wsReconnectTimer);
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'frame') handleFrame(msg);
    } catch (err) {
      console.error('[WS] Parse error:', err);
    }
  };

  ws.onclose = () => {
    setConnectionStatus('off', 'Reconnecting…');
    scheduleReconnect();
  };

  ws.onerror = () => ws.close();
}

function scheduleReconnect() {
  clearTimeout(wsReconnectTimer);
  wsReconnectTimer = setTimeout(() => {
    wsReconnectDelay = Math.min(wsReconnectDelay * 1.5, WS_MAX_DELAY);
    connectWebSocket();
  }, wsReconnectDelay);
}

function setConnectionStatus(state, label) {
  const dot = document.getElementById('connection-dot');
  const lbl = document.getElementById('connection-label');
  if (dot) dot.className = 'status-dot' + (state === 'live' ? ' live' : '');
  if (lbl) lbl.textContent = label;
}

// ─── Frame Handler (Tab 1) ─────────────────────────────────────────────────────

function handleFrame(msg) {
  // 1. Show frame
  const img         = document.getElementById('live-canvas');
  const placeholder = document.getElementById('video-placeholder');
  if (msg.data) {
    img.src           = msg.data;
    img.style.display = 'block';
    placeholder.style.display = 'none';
  }

  // 2. Mode badge
  const badge = document.getElementById('mode-badge');
  if (badge) {
    const isLive = msg.data && !msg.data.includes('mock');
    badge.className = 'badge ' + (isLive ? 'badge-live' : 'badge-mock');
    badge.innerHTML = `<span class="badge-dot"></span>${isLive ? 'LIVE' : 'MOCK'}`;
  }

  // 3. Header counter
  const stats = msg.stats || {};
  const hdr   = document.getElementById('header-occupied');
  if (hdr && stats.total > 0) hdr.textContent = `${stats.occupied} / ${stats.total}`;

  // 4. Summary counts
  setText('count-occupied', stats.occupied ?? '—');
  setText('count-vacant',   stats.vacant   ?? '—');

  // 5. Workspace grid — use ONLY what is in the current frame
  updateWorkspaceGrid(msg.workspaces || {});
}

// Dynamic workspace grid initialization based on camera_config/workspaces list
let activeWorkspaceIds = [];
let gridInitialized = false;

async function initWorkspaceGrid() {
  const grid = document.getElementById('ws-grid');
  if (!grid || gridInitialized) return;

  try {
    const res = await fetch('/api/workspaces');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const workspaces = data.workspaces || [];

    workspaces.sort((a, b) => a.ws_id.localeCompare(b.ws_id));

    grid.innerHTML = '';
    activeWorkspaceIds = [];

    workspaces.forEach(ws => {
      const wsId = ws.ws_id;
      const num  = parseInt(wsId.replace('ws_', ''), 10);
      const cell = document.createElement('div');
      cell.className = 'ws-cell';
      cell.id        = `ws-cell-${wsId}`;
      cell.title     = ws.label || wsId;
      cell.innerHTML = `
        <span class="ws-icon">●</span>
        <span class="ws-num">${num}</span>
      `;
      grid.appendChild(cell);
      activeWorkspaceIds.push(wsId);
    });

    const maxCol = Math.max(...workspaces.map(w => w.grid_col), 0);
    const cols = maxCol + 1;
    grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

    gridInitialized = true;
  } catch (e) {
    console.error('[GridInit] Failed:', e);
  }
}

function updateWorkspaceGrid(workspaces) {
  const grid = document.getElementById('ws-grid');
  if (!grid) return;

  if (!gridInitialized) {
    initWorkspaceGrid();
    return;
  }

  activeWorkspaceIds.forEach(wsId => {
    const cell  = document.getElementById(`ws-cell-${wsId}`);
    if (!cell) return;
    const state = workspaces[wsId] || 'vacant';

    cell.className  = `ws-cell ${state}`;
    cell.title      = `${wsId}: ${state}`;
    const icon = cell.querySelector('.ws-icon');
    if (icon) icon.textContent = state === 'occupied' ? '●' : '○';
  });
}


// ─── Analytics (Tab 2) ────────────────────────────────────────────────────────

async function loadAnalytics() {
  try {
    const res  = await fetch('/api/analytics?days=7');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    analyticsLoaded = true;
    renderAnalytics(data);
  } catch (e) {
    console.error('[Analytics] Failed:', e);
  }
}

function renderAnalytics(data) {
  renderPeakHoursChart(data.peak_hours || []);
  renderDowChart(data.day_of_week || []);
  renderEfficiencyList(data.startup_efficiency || []);
  renderPerWsChart(data.workspace_utilization || []);
  renderWsTable(data.workspace_utilization || []);
}

function renderPeakHoursChart(peakHours) {
  const labels = peakHours.map(h => h.hour_label || `${h.hour}:00`);
  const values = peakHours.map(h => Math.round(h.avg_occupancy * 100));
  const colors = peakHours.map(h =>
    h.category === 'peak'     ? 'rgba(220,38,38,0.75)' :
    h.category === 'off_peak' ? 'rgba(22,163,74,0.65)' :
                                 'rgba(37,99,235,0.65)'
  );
  destroyChart('chart-peak-hours');
  const ctx = document.getElementById('chart-peak-hours').getContext('2d');
  charts['chart-peak-hours'] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Occupancy %', data: values, backgroundColor: colors, borderRadius: 6, borderSkipped: false }] },
    options: chartOptions('Occupancy %', 100),
  });
}

function renderDowChart(dow) {
  const labels = dow.map(d => d.day.slice(0, 3));
  const values = dow.map(d => Math.round(d.avg_occupancy * 100));
  destroyChart('chart-dow');
  const ctx = document.getElementById('chart-dow').getContext('2d');
  charts['chart-dow'] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{
      label: 'Occupancy %', data: values,
      borderColor: '#FF5C00', backgroundColor: 'rgba(255,92,0,0.08)',
      fill: true, tension: 0.4,
      pointBackgroundColor: '#FF5C00', pointRadius: 5,
    }]},
    options: chartOptions('Occupancy %', 100),
  });
}

function renderPerWsChart(wsUtils) {
  const top    = [...wsUtils].slice(0, 15);
  const labels = top.map(w => (w.label || w.ws_id).replace('Desk Space ', ''));
  const values = top.map(w => Math.round((w.utilization_rate || 0) * 100));
  const colors = values.map(v =>
    v >= 50 ? 'rgba(22,163,74,0.75)'  :
    v >= 25 ? 'rgba(217,119,6,0.75)'  :
              'rgba(220,38,38,0.75)'
  );
  destroyChart('chart-per-ws');
  const ctx = document.getElementById('chart-per-ws').getContext('2d');
  charts['chart-per-ws'] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Utilization %', data: values, backgroundColor: colors, borderRadius: 5, borderSkipped: false }]},
    options: { ...chartOptions('Utilization %', 100), indexAxis: 'y' },
  });
}

function renderEfficiencyList(efficiency) {
  const el = document.getElementById('efficiency-list');
  if (!el) return;
  if (!efficiency.length) { el.innerHTML = '<div style="color:var(--text-muted);">No data</div>'; return; }

  el.innerHTML = efficiency.map(e => {
    const pct = Math.round((e.score || 0) * 100);
    const cls = pct >= 50 ? 'good' : pct >= 25 ? 'ok' : 'poor';
    return `
      <div>
        <div class="efficiency-item-header">
          <span class="startup-name">${e.startup}</span>
          <span class="score">${e.avg_used} / ${e.allocated} spaces · ${pct}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill ${cls}" style="width:${pct}%"></div>
        </div>
      </div>
    `;
  }).join('');
}

function renderWsTable(wsUtils) {
  const tbody = document.getElementById('ws-table-body');
  if (!tbody) return;
  if (!wsUtils.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);padding:24px;text-align:center;">No data</td></tr>';
    return;
  }

  const maxHrs = Math.max(...wsUtils.map(w => w.avg_daily_hours || 0), 1);

  tbody.innerHTML = wsUtils.map(ws => {
    const hrs    = ws.avg_daily_hours || 0;
    const pct    = Math.round((ws.utilization_rate || 0) * 100);
    const barPct = Math.min(100, (hrs / 8) * 100);
    const cls    = pct >= 50 ? 'good' : pct >= 25 ? 'ok' : 'poor';

    const statusMap = {
      'active':       '<span class="status-badge active">✅ Active</span>',
      'underused':    '<span class="status-badge underused">⚠️ Underused</span>',
      'reassignable': '<span class="status-badge reassignable">🔴 Reassignable</span>',
    };

    return `
      <tr>
        <td style="font-weight:600;">${ws.label || ws.ws_id}</td>
        <td style="color:var(--text-secondary);">${ws.startup_name || ws.startup}</td>
        <td>
          <div class="hours-bar">
            <div class="bar-track">
              <div class="bar-fill ${cls}" style="width:${barPct}%"></div>
            </div>
            <span class="bar-label">${hrs.toFixed(1)}h</span>
          </div>
        </td>
        <td style="font-family:'JetBrains Mono',monospace;font-weight:600;">
          ${ws.utilization_pct || pct + '%'}
        </td>
        <td style="color:var(--text-secondary);">
          ${ws.consecutive_vacant_days > 0 ? `${ws.consecutive_vacant_days}d` : '—'}
        </td>
        <td>${statusMap[ws.status] || ws.status}</td>
      </tr>
    `;
  }).join('');
}

// ─── Space Optimization (Tab 3) ────────────────────────────────────────────────

async function loadOptimize() {
  // Load startups for the selector
  if (!allStartups.length) {
    try {
      const res = await fetch('/api/workspaces');
      const d   = await res.json();
      allStartups = d.startups || [];
      populateStartupSelect(allStartups);
      renderStartupSummary(allStartups, d.workspaces || []);
    } catch(e) { console.error('[Optimize] Failed to load startups:', e); }
  }
  // Load startup summary cards via recommendations report
  try {
    const res = await fetch('/api/recommendations?days=7');
    const d   = await res.json();
    renderStartupReportCards(d.startup_reports || []);
  } catch(e) {}
}

function populateStartupSelect(startups) {
  const sel = document.getElementById('req-startup-select');
  if (!sel) return;
  sel.innerHTML = '<option value="">Select startup…</option>' +
    startups.map(s => `<option value="${s.startup_id}">${s.name}</option>`).join('');
}

function renderStartupReportCards(reports) {
  const row = document.getElementById('startup-summary-row');
  if (!row || !reports.length) return;

  row.innerHTML = reports.map(r => {
    const s   = r.summary || {};
    const tag = s.reassignable_count > 0
      ? `<span class="ss-tag reassignable">${s.reassignable_count} spaces can be reassigned</span>`
      : `<span class="ss-tag efficient">Fully utilized</span>`;
    return `
      <div class="startup-summary-card">
        <div class="ss-name">${r.startup_name || r.startup}</div>
        <div class="ss-stat">${s.effective_usage || '—'}</div>
        <div class="ss-sub">spaces effectively used (7-day avg)</div>
        ${tag}
      </div>
    `;
  }).join('');
}

async function runRecommendation() {
  const startupId    = document.getElementById('req-startup-select')?.value;
  const spacesNeeded = parseInt(document.getElementById('req-spaces-count')?.value) || 5;

  if (!startupId) {
    alert('Please select a requesting startup first.');
    return;
  }

  const emptyState = document.getElementById('opt-empty-state');
  const results    = document.getElementById('rec-results');
  if (emptyState) emptyState.style.display = 'none';
  if (results)    results.style.display    = 'none';

  try {
    const res = await fetch(`/api/recommend-for/${startupId}?spaces_needed=${spacesNeeded}&days=7`);
    const d   = await res.json();
    currentRec = d;
    renderRecommendations(d);
    if (results) results.style.display = 'block';
  } catch(e) {
    console.error('[Rec] Failed:', e);
    alert('Failed to load recommendations. Make sure the server is running.');
  }
}
window.runRecommendation = runRecommendation;

function renderRecommendations(rec) {
  const banner    = document.getElementById('rec-match-banner');
  const grid      = document.getElementById('rec-grid');
  const confirmBar = document.getElementById('confirm-bar');
  const confirmSummary = document.getElementById('confirm-summary');

  // Match banner
  const matchColors = { exact: '#16A34A', partial: '#D97706', none: '#DC2626' };
  const matchIcons  = { exact: '✅', partial: '⚠️', none: '❌' };
  const matchLabels = {
    exact:   `Exact match found — ${rec.spaces_found} space(s) available`,
    partial: `Partial match — found ${rec.spaces_found} of ${rec.spaces_needed} requested`,
    none:    'No available spaces found — all spaces are actively utilized',
  };

  if (banner) {
    banner.innerHTML = `
      <div style="
        display:flex;align-items:center;gap:10px;
        padding:14px 18px;border-radius:14px;
        background:${matchColors[rec.match_status]}18;
        border:1px solid ${matchColors[rec.match_status]}40;
        font-size:0.88rem;font-weight:500;
      ">
        <span style="font-size:1.2rem;">${matchIcons[rec.match_status]}</span>
        <span>${matchLabels[rec.match_status]}</span>
      </div>`;
  }

  // Recommendation cards
  if (grid) {
    if (!rec.recommendation?.length) {
      grid.innerHTML = '';
    } else {
      grid.innerHTML = rec.recommendation.map(ws => `
        <div class="rec-card">
          <div class="rec-card-top">
            <div>
              <div class="rec-label">${ws.label}</div>
              <div class="rec-owner">Currently: ${ws.current_owner_name || ws.current_owner}</div>
            </div>
            <span class="rec-util-badge">${ws.utilization_pct}</span>
          </div>
          <p class="rec-reason">${ws.reason}</p>
          <div class="rec-stats">
            <div class="rec-stat">
              <div class="rs-val">${ws.avg_daily_hours}h</div>
              <div class="rs-lbl">Daily avg</div>
            </div>
            <div class="rec-stat">
              <div class="rs-val">${ws.consecutive_vacant > 0 ? ws.consecutive_vacant + 'd' : '—'}</div>
              <div class="rs-lbl">Vacant streak</div>
            </div>
          </div>
        </div>
      `).join('');
    }
  }

  // Confirm bar
  if (confirmBar && rec.recommendation?.length) {
    const reqName = allStartups.find(s => s.startup_id === rec.requesting_startup)?.name || rec.requesting_startup;
    if (confirmSummary) {
      confirmSummary.innerHTML =
        `Reassign <strong>${rec.spaces_found}</strong> space(s) to <strong>${reqName}</strong>`;
    }
    confirmBar.style.display = 'flex';
  } else if (confirmBar) {
    confirmBar.style.display = 'none';
  }
}

async function generateLetter() {
  if (!currentRec) return;
  const startupId = currentRec.requesting_startup;
  const spacesNeeded = currentRec.spaces_needed;
  try {
    const res = await fetch(`/api/assignment-letter?requesting_startup=${startupId}&spaces_needed=${spacesNeeded}&days=7`);
    const d   = await res.json();
    showLetterModal(d.letter || 'Could not generate letter.');
  } catch(e) {
    alert('Failed to generate letter.');
  }
}
window.generateLetter = generateLetter;

async function confirmReassignment() {
  if (!currentRec || !currentRec.recommendation?.length) return;
  const wsIds      = currentRec.recommendation.map(w => w.ws_id);
  const newStartup = currentRec.requesting_startup;
  const reqName    = allStartups.find(s => s.startup_id === newStartup)?.name || newStartup;

  if (!confirm(`Confirm reassignment of ${wsIds.length} workspace(s) to ${reqName}? This will update the database.`)) return;

  try {
    const res = await fetch('/api/reassign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ws_ids: wsIds, new_startup_id: newStartup }),
    });
    const d = await res.json();
    if (d.status === 'confirmed') {
      alert(`✅ Successfully reassigned ${d.reassigned_count} workspace(s) to ${reqName}!`);
      currentRec = null;
      document.getElementById('rec-results').style.display = 'none';
      document.getElementById('opt-empty-state').style.display = 'block';
      // Reload optimize tab
      document.querySelector('[onclick="switchTab(\'optimize\')"]')?.click();
    }
  } catch(e) {
    alert('Reassignment failed. Please try again.');
  }
}
window.confirmReassignment = confirmReassignment;

function showLetterModal(letterText) {
  const modal   = document.getElementById('letter-modal');
  const content = document.getElementById('letter-content');
  if (content) content.textContent = letterText;
  if (modal)   modal.style.display = 'flex';
}

function closeLetterModal() {
  const modal = document.getElementById('letter-modal');
  if (modal) modal.style.display = 'none';
}
window.closeLetterModal = closeLetterModal;

function copyLetter() {
  const content = document.getElementById('letter-content')?.textContent || '';
  navigator.clipboard.writeText(content)
    .then(() => alert('Letter copied to clipboard!'))
    .catch(() => {});
}
window.copyLetter = copyLetter;

// ─── Chart Helpers ─────────────────────────────────────────────────────────────

function chartOptions(yLabel = '%', yMax = 100) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(30,30,30,0.95)',
        borderColor: 'rgba(255,255,255,0.08)',
        borderWidth: 1,
        titleColor: '#F0F0F0',
        bodyColor: '#8A8A8A',
        padding: 10,
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: '#666', font: { size: 11, family: 'Space Grotesk' } },
      },
      y: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: '#666', font: { size: 11 }, callback: v => `${v}%` },
        min: 0, max: yMax,
      }
    }
  };
}

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

// ─── Utilities ─────────────────────────────────────────────────────────────────

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ─── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initWorkspaceGrid();
  connectWebSocket();
});
