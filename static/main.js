/**
 * main.js — OccuSense AI Dashboard (v6 — Proximity Chair Occupancy)
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let ws               = null;
let wsReconnectTimer = null;
let wsReconnectDelay = 1500;
const WS_MAX_DELAY   = 15000;
let frameCounter     = 0;
let currentTab       = 'live';
let heatmapMode      = false;

// ─── Tab Switcher ─────────────────────────────────────────────────────────────

function switchTab(tabName) {
  currentTab = tabName;
  
  // Update nav buttons
  document.getElementById('nav-live').classList.toggle('active', tabName === 'live');
  document.getElementById('nav-analytics').classList.toggle('active', tabName === 'analytics');
  
  // Update panels
  document.getElementById('panel-live').classList.toggle('active', tabName === 'live');
  document.getElementById('panel-analytics').classList.toggle('active', tabName === 'analytics');
  
  if (tabName === 'analytics') {
    fetchAnalyticsData();
  }
}
window.switchTab = switchTab;

// ─── WebSocket ─────────────────────────────────────────────────────────────────

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url   = `${proto}://${location.host}/ws/live?camera_id=cam_floor2`;
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

// ─── Frame & WS Payload Handler ───────────────────────────────────────────────

function handleFrame(msg) {
  frameCounter++;

  // 1. Render annotated video frame
  const img         = document.getElementById('live-canvas');
  const placeholder = document.getElementById('video-placeholder');
  if (msg.data) {
    img.src           = msg.data;
    img.style.display = 'block';
    placeholder.style.display = 'none';
  }

  // 2. Sidebar Frame Counter
  setText('frame-count', frameCounter);

  // 3. Extract counts
  const totalChairs    = msg.chairs ? msg.chairs.total : 0;
  const occupiedChairs = msg.chairs ? msg.chairs.occupied : 0;
  const vacantChairs   = msg.chairs ? msg.chairs.vacant : 0;
  const totalPersons   = msg.total_persons || 0;
  const dwellTimes     = msg.dwell_times || {};

  // 4. Update Big Count Cards
  setText('total-chairs',    totalChairs);
  setText('occupied-chairs', occupiedChairs);
  setText('vacant-chairs',   vacantChairs);

  // 5. Update Occupancy Percentage Bar
  const pct = totalChairs > 0 ? Math.round((occupiedChairs / totalChairs) * 100) : 0;
  setText('occupancy-pct', `${pct}%`);
  const bar = document.getElementById('occupancy-bar');
  if (bar) {
    bar.style.width = `${pct}%`;
    if (pct >= 80) {
      bar.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
    } else if (pct >= 50) {
      bar.style.background = 'linear-gradient(90deg, #f59e0b, #d97706)';
    } else {
      bar.style.background = 'linear-gradient(90deg, #22c55e, #16a34a)';
    }
  }

  // Highlight occupied card if someone is active
  const occCard = document.querySelector('.occupied-card');
  if (occCard) {
    if (occupiedChairs > 0) {
      occCard.classList.add('has-occupancy');
    } else {
      occCard.classList.remove('has-occupancy');
    }
  }
}

// ─── Heatmap Toggle ───────────────────────────────────────────────────────────

function toggleHeatmap() {
  heatmapMode = !heatmapMode;
  const btn = document.getElementById('btn-toggle-heatmap');
  if (btn) {
    if (heatmapMode) {
      btn.textContent = '📹 Show Live Feed';
      btn.className = 'btn btn-primary';
    } else {
      btn.textContent = '🔥 Show Heatmap';
      btn.className = 'btn btn-secondary';
    }
  }
  
  // Call API to toggle heatmap on server
  fetch('/api/heatmap/toggle', { method: 'POST' })
    .then(res => res.json())
    .then(data => console.log('[Heatmap] Toggled overlay state:', data))
    .catch(err => console.error('[Heatmap] Toggle error:', err));
}
window.toggleHeatmap = toggleHeatmap;

// ─── Analytics Reports ────────────────────────────────────────────────────────

function fetchAnalyticsData() {
  // 1. Get historical chair occupancy log averages (Hourly Chart + Circular Ratio)
  fetch('/api/chairs/history')
    .then(res => res.json())
    .then(history => {
      renderHourlyChart(history);
      renderCircularChart(history);
    })
    .catch(err => console.error('[Analytics] History load error:', err));

  // 2. Get startup space utilization report (Contract vs Reality)
  fetch('/api/startups/utilization')
    .then(res => res.json())
    .then(data => renderUtilizationTable(data))
    .catch(err => console.error('[Analytics] Utilization load error:', err));
}

function renderHourlyChart(history) {
  const container = document.getElementById('hourly-chart-container');
  if (!container) return;
  if (!history || history.length === 0) {
    container.innerHTML = '<div class="chart-placeholder">No historical data logs found.</div>';
    return;
  }

  const maxVal = Math.max(...history.map(d => d.avg_total), 12);
  const width = 800;
  const height = 220;
  const padding = 40;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;
  const barWidth = chartWidth / history.length - 10;

  let bars = '';
  let labels = '';
  
  history.forEach((d, i) => {
    const x = padding + i * (chartWidth / history.length) + 5;
    // Total bar height (grey background bar)
    const totalHeight = (d.avg_total / maxVal) * chartHeight;
    const totalY = height - padding - totalHeight;
    
    // Occupied bar height (blue/purple foreground bar)
    const occHeight = (d.avg_occupied / maxVal) * chartHeight;
    const occY = height - padding - occHeight;
    
    bars += `
      <!-- Total Bar -->
      <rect x="${x}" y="${totalY}" width="${barWidth}" height="${totalHeight}" fill="rgba(0,0,0,0.04)" rx="4" />
      <!-- Occupied Bar -->
      <rect x="${x}" y="${occY}" width="${barWidth}" height="${occHeight}" fill="url(#barGradient)" rx="4" />
      <!-- Tooltip trigger -->
      <rect x="${x}" y="${totalY}" width="${barWidth}" height="${totalHeight}" fill="transparent" style="cursor:pointer;">
        <title>${d.hour}:00\nAverage Occupied: ${d.avg_occupied}/${d.avg_total}</title>
      </rect>
    `;
    
    // Hour label
    labels += `<text x="${x + barWidth/2}" y="${height - 15}" fill="#64748b" font-size="11" text-anchor="middle">${d.hour}:00</text>`;
  });

  container.innerHTML = `
    <svg width="100%" height="100%" viewBox="0 0 ${width} ${height}">
      <defs>
        <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#0052cc" />
          <stop offset="100%" stop-color="#00a2fe" />
        </linearGradient>
      </defs>
      <!-- Grid Lines -->
      <line x1="${padding}" y1="${padding}" x2="${width - padding}" y2="${padding}" stroke="rgba(0,0,0,0.03)" stroke-dasharray="4" />
      <line x1="${padding}" y1="${padding + chartHeight/2}" x2="${width - padding}" y2="${padding + chartHeight/2}" stroke="rgba(0,0,0,0.03)" stroke-dasharray="4" />
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#cbd5e1" />
      
      <!-- Bars -->
      ${bars}
      <!-- Labels -->
      ${labels}
      <!-- Y-Axis max label -->
      <text x="${padding - 10}" y="${padding + 5}" fill="#64748b" font-size="10" text-anchor="end">${Math.round(maxVal)}</text>
      <text x="${padding - 10}" y="${padding + chartHeight/2 + 5}" fill="#64748b" font-size="10" text-anchor="end">${Math.round(maxVal/2)}</text>
      <text x="${padding - 10}" y="${height - padding + 5}" fill="#64748b" font-size="10" text-anchor="end">0</text>
    </svg>
  `;
}

function renderUtilizationTable(data) {
  const tbody = document.getElementById('utilization-table-body');
  if (!tbody) return;
  if (!data || data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No startup space utilization records found.</td></tr>`;
    return;
  }

  let html = '';
  data.forEach(s => {
    let recClass = '';
    if (s.recommendation.includes('High')) {
      recClass = 'rec-high';
    } else if (s.recommendation.includes('Downsize')) {
      recClass = 'rec-medium';
    } else {
      recClass = 'rec-low';
    }

    html += `
      <tr>
        <td><strong>${s.name}</strong></td>
        <td>${s.contracted} desks</td>
        <td>${s.actual_used} desks</td>
        <td><span class="util-badge">${s.utilization_pct}</span></td>
        <td><span class="rec-badge ${recClass}">${s.recommendation}</span></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function renderCircularChart(history) {
  if (!history || history.length === 0) return;
  
  let totalSum = 0;
  let occSum = 0;
  history.forEach(d => {
    totalSum += d.avg_total;
    occSum += d.avg_occupied;
  });
  
  const avgRate = totalSum > 0 ? Math.round((occSum / totalSum) * 100) : 0;
  
  const circleProgress = document.getElementById('ratio-circle-progress');
  const circleText = document.getElementById('ratio-circle-text');
  const circleStats = document.getElementById('ratio-circle-stats');
  
  if (circleProgress) {
    // Circumference is 100
    circleProgress.setAttribute('stroke-dasharray', `${avgRate}, 100`);
  }
  if (circleText) {
    circleText.textContent = `${avgRate}%`;
  }
  if (circleStats) {
    circleStats.innerHTML = `<strong>${avgRate}%</strong> Average Occupancy Rate<br><span style="font-size:0.75rem; color:var(--text-muted); font-weight:400; margin-top:2px; display:inline-block;">Based on past 7 days of logs</span>`;
  }
}

// ─── Add Startup Modal Handlers ───────────────────────────────────────────────

function showAddStartupModal() {
  const modal = document.getElementById('add-startup-modal');
  if (modal) {
    document.getElementById('startup-name').value = '';
    document.getElementById('startup-chairs').value = '';
    modal.style.display = 'flex';
  }
}
window.showAddStartupModal = showAddStartupModal;

function closeAddStartupModal() {
  const modal = document.getElementById('add-startup-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}
window.closeAddStartupModal = closeAddStartupModal;

function submitAddStartup() {
  const nameInput = document.getElementById('startup-name');
  const chairsInput = document.getElementById('startup-chairs');
  if (!nameInput || !chairsInput) return;

  const name = nameInput.value.trim();
  const chairs = parseInt(chairsInput.value);

  if (!name) {
    alert("Please enter a startup name.");
    return;
  }
  if (isNaN(chairs) || chairs <= 0) {
    alert("Please enter a valid number of contracted chairs.");
    return;
  }

  fetch('/api/startups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name, contracted: chairs })
  })
  .then(res => {
    if (!res.ok) throw new Error("Failed to register startup");
    return res.json();
  })
  .then(data => {
    console.log("[AddStartup] Registered:", data);
    closeAddStartupModal();
    // Refresh table immediately
    fetchAnalyticsData();
  })
  .catch(err => {
    console.error("[AddStartup] Error:", err);
    alert("Error registering startup: " + err.message);
  });
}
window.submitAddStartup = submitAddStartup;

// ─── Utilities ─────────────────────────────────────────────────────────────────

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ─── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  connectWebSocket();
});
