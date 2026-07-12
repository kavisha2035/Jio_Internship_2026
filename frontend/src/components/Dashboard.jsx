import React, { useState, useEffect } from 'react';
import AddStartupModal from './AddStartupModal';

function PeakHoursChart({ history }) {
  if (!history || history.length === 0) {
    return <div className="chart-placeholder">No historical data logs found.</div>;
  }
  const maxVal = Math.max(...history.map(d => d.avg_total), 12);
  const width = 800;
  const height = 220;
  const padding = 40;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;
  const barWidth = chartWidth / history.length - 10;

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`}>
      <defs>
        <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#0052cc" />
          <stop offset="100%" stopColor="#00a2fe" />
        </linearGradient>
      </defs>
      {/* Grid Lines */}
      <line x1={padding} y1={padding} x2={width - padding} y2={padding} stroke="rgba(0,0,0,0.03)" strokeDasharray="4" />
      <line x1={padding} y1={padding + chartHeight/2} x2={width - padding} y2={padding + chartHeight/2} stroke="rgba(0,0,0,0.03)" strokeDasharray="4" />
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#cbd5e1" />
      
      {/* Bars */}
      {history.map((d, i) => {
        const x = padding + i * (chartWidth / history.length) + 5;
        const totalBarHeight = (d.avg_total / maxVal) * chartHeight;
        const totalY = height - padding - totalBarHeight;

        const occBarHeight = (d.avg_occupied / maxVal) * chartHeight;
        const occY = height - padding - occBarHeight;

        return (
          <React.Fragment key={i}>
            <rect x={x} y={totalY} width={barWidth} height={totalBarHeight} fill="rgba(0,0,0,0.04)" rx="4" />
            <rect x={x} y={occY} width={barWidth} height={occBarHeight} fill="url(#barGradient)" rx="4" />
            <rect x={x} y={totalY} width={barWidth} height={totalBarHeight} fill="transparent" style={{ cursor: 'pointer' }}>
              <title>{`${d.hour}:00\nAverage Occupied: ${d.avg_occupied}/${d.avg_total}`}</title>
            </rect>
          </React.Fragment>
        );
      })}

      {/* Labels */}
      {history.map((d, i) => {
        const x = padding + i * (chartWidth / history.length) + 5;
        return (
          <text key={i} x={x + barWidth / 2} y={height - 15} fill="#64748b" fontSize="11" textAnchor="middle">
            {`${d.hour}:00`}
          </text>
        );
      })}

      {/* Y-Axis Labels */}
      <text x={padding - 10} y={padding + 5} fill="#64748b" fontSize="10" textAnchor="end">{Math.round(maxVal)}</text>
      <text x={padding - 10} y={padding + chartHeight / 2 + 5} fill="#64748b" fontSize="10" textAnchor="end">{Math.round(maxVal / 2)}</text>
      <text x={padding - 10} y={height - padding + 5} fill="#64748b" fontSize="10" textAnchor="end">0</text>
    </svg>
  );
}

function CircularOccupancyChart({ history }) {
  if (!history || history.length === 0) {
    return <div className="circular-stats-info">Loading occupancy ratio...</div>;
  }
  let totalSum = 0;
  let occSum = 0;
  history.forEach(d => {
    totalSum += d.avg_total;
    occSum += d.avg_occupied;
  });
  const avgRate = totalSum > 0 ? Math.round((occSum / totalSum) * 100) : 0;

  return (
    <div className="circular-chart-wrapper">
      <div className="circular-chart-container">
        <svg viewBox="0 0 36 36" className="circular-svg">
          <defs>
            <linearGradient id="circleGradient" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#0052cc" />
              <stop offset="100%" stopColor="#0066fe" />
            </linearGradient>
          </defs>
          <path className="circle-bg"
            d="M18 2.0845
              a 15.9155 15.9155 0 0 1 0 31.831
              a 15.9155 15.9155 0 0 1 0 -31.831"
          />
          <path className="circle-fill"
            strokeDasharray={`${avgRate}, 100`}
            d="M18 2.0845
              a 15.9155 15.9155 0 0 1 0 31.831
              a 15.9155 15.9155 0 0 1 0 -31.831"
          />
          <text x="18" y="20.35" className="circle-percentage">{avgRate}%</text>
        </svg>
      </div>
      <div className="circular-stats-info">
        <strong>{avgRate}%</strong> Average Occupancy Rate
        <br />
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 400, marginTop: '2px', display: 'inline-block' }}>
          Based on past 7 days of logs
        </span>
      </div>
    </div>
  );
}

export default function Dashboard({ cameraData, connectionStatus, frameCount, onBackToProduct }) {
  const [activeTab, setActiveTab] = useState('live');
  const [heatmapMode, setHeatmapMode] = useState(false);
  const [historyData, setHistoryData] = useState([]);
  const [utilizationData, setUtilizationData] = useState([]);
  const [showAddModal, setShowAddModal] = useState(false);

  // Load analytics when the reports tab is selected
  const fetchAnalytics = () => {
    fetch('/api/chairs/history')
      .then(res => res.json())
      .then(data => {
        setHistoryData(Array.isArray(data) ? data : []);
      })
      .catch(err => {
        console.error('[Analytics] History load error:', err);
        setHistoryData([]);
      });

    fetch('/api/startups/utilization')
      .then(res => res.json())
      .then(data => {
        setUtilizationData(Array.isArray(data) ? data : []);
      })
      .catch(err => {
        console.error('[Analytics] Utilization load error:', err);
        setUtilizationData([]);
      });
  };

  useEffect(() => {
    if (activeTab === 'reports') {
      fetchAnalytics();
    }
  }, [activeTab]);

  const toggleHeatmap = () => {
    setHeatmapMode(!heatmapMode);
    fetch('/api/heatmap/toggle', { method: 'POST' })
      .then(res => res.json())
      .then(data => console.log('[Heatmap] Toggled state:', data))
      .catch(err => console.error('[Heatmap] Toggle error:', err));
  };

  // Derive counts from camera payload or fallback
  const totalChairs = cameraData.chairs ? cameraData.chairs.total : 0;
  const occupiedChairs = cameraData.chairs ? cameraData.chairs.occupied : 0;
  const vacantChairs = cameraData.chairs ? cameraData.chairs.vacant : 0;

  const occupancyRate = totalChairs > 0 ? Math.round((occupiedChairs / totalChairs) * 100) : 0;

  // Compute color bar background
  let progressBackground = 'linear-gradient(90deg, #22c55e, #16a34a)';
  if (occupancyRate >= 80) {
    progressBackground = 'linear-gradient(90deg, #ef4444, #dc2626)';
  } else if (occupancyRate >= 50) {
    progressBackground = 'linear-gradient(90deg, #f59e0b, #d97706)';
  }

  return (
    <div className="app-shell">
      {/* Sidebar Panel */}
      <aside className="sidebar">
        <div className="sidebar-logo-container">
          <div className="sidebar-logo"></div>
          <div className="sidebar-title-group">
            <span className="sidebar-title">OccuSense AI</span>
            <span className="sidebar-subtitle">Chair Detection</span>
          </div>
        </div>

        <div className="sidebar-nav">
          <p className="nav-section-title">Detection</p>
          <button
            className={`nav-item-btn ${activeTab === 'live' ? 'active' : ''}`}
            onClick={() => setActiveTab('live')}
          >
            <span className="nav-icon">🎦</span>Live Feed
          </button>
          <button
            className={`nav-item-btn ${activeTab === 'reports' ? 'active' : ''}`}
            onClick={() => setActiveTab('reports')}
          >
            <span className="nav-icon">📊</span>Reports & Charts
          </button>
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-info">
            <span className="info-label">Model</span>
            <span className="info-value">YOLOv8n</span>
          </div>
          <div className="sidebar-info">
            <span className="info-label">Frames</span>
            <span className="info-value">{frameCount}</span>
          </div>
        </div>
      </aside>

      {/* Main Panel Content */}
      <div className="main-content">
        {/* Header Bar */}
        <header className="top-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <button className="btn btn-secondary" onClick={onBackToProduct} style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
              &larr; Back to Product Info
            </button>
            <div className="header-title">
              <h1>OccuSense AI</h1>
              <p>Real-time Chair Occupancy Detection</p>
            </div>
          </div>

          <div className="header-right">
            <div className="status-pill">
              <span className={`status-dot ${connectionStatus === 'Connected' ? 'live' : ''}`}></span>
              <span>{connectionStatus}</span>
            </div>
          </div>
        </header>

        <main className="page-area">
          {activeTab === 'live' ? (
          <section className="tab-panel active">
            <div className="live-layout">
              {/* Camera Video card */}
              <div className="card video-card">
                <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h2 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Live Camera Feed</h2>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      className={`btn ${heatmapMode ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={toggleHeatmap}
                    >
                      {heatmapMode ? '📹 Show Live Feed' : '🔥 Show Heatmap'}
                    </button>
                    <span className="live-badge">● LIVE</span>
                  </div>
                </div>

                <div className="video-wrapper">
                  {cameraData.data ? (
                    <img
                      src={cameraData.data}
                      alt="Annotated Camera Frame"
                      className="live-canvas"
                      style={{ display: 'block', borderRadius: '4px' }}
                    />
                  ) : (
                    <div className="video-placeholder">
                      <span className="spinner"></span>
                      <span>Loading Real-time Camera Feed...</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Sidebar Stats Panel */}
              <div className="chair-panel">
                <div className="panel-title">Overview</div>

                <div className="stat-cards">
                  <div className="big-stat-card">
                    <div className="big-stat-icon">🪑</div>
                    <div className="big-stat-value">{totalChairs}</div>
                    <div className="big-stat-label">Total Chairs</div>
                  </div>
                  <div className={`big-stat-card occupied-card ${occupiedChairs > 0 ? 'has-occupancy' : ''}`}>
                    <div className="big-stat-icon">👤</div>
                    <div className="big-stat-value">{occupiedChairs}</div>
                    <div className="big-stat-label">Occupied</div>
                  </div>
                  <div className="big-stat-card vacant-card">
                    <div className="big-stat-icon">✅</div>
                    <div className="big-stat-value">{vacantChairs}</div>
                    <div className="big-stat-label">Available</div>
                  </div>
                </div>

                {/* Occupancy bar */}
                <div className="occupancy-bar-container">
                  <div className="occ-bar-header">
                    <span>Occupancy Rate</span>
                    <span className="occ-pct">{occupancyRate}%</span>
                  </div>
                  <div className="occ-bar-track">
                    <div
                      className="occ-bar-fill"
                      style={{ width: `${occupancyRate}%`, background: progressBackground }}
                    ></div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        ) : (
          <section className="tab-panel active">
            <div className="analytics-layout">
              {/* Hourly Chart */}
              <div className="card analytics-card">
                <div className="card-header">
                  <h2>Peak Occupancy Hours (Hourly Average)</h2>
                </div>
                <div className="chart-wrapper">
                  <div className="chart-container">
                    <PeakHoursChart history={historyData} />
                  </div>
                </div>
              </div>

              <div className="analytics-grid">
                {/* Space Utilization Table */}
                <div className="card table-card">
                  <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2>Startup Space Utilization (Contract vs Reality)</h2>
                    <div className="card-header-actions">
                      <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
                        ➕ Add Startup
                      </button>
                    </div>
                  </div>
                  <div className="table-wrapper">
                    <table className="report-table">
                      <thead>
                        <tr>
                          <th>Startup Name</th>
                          <th>Contracted</th>
                          <th>Actual Used</th>
                          <th>Utilization %</th>
                          <th>Renewal Recommendation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Array.isArray(utilizationData) && utilizationData.length > 0 ? (
                          utilizationData.map((s, idx) => {
                            let recClass = '';
                            if (s.recommendation.includes('High')) {
                              recClass = 'rec-high';
                            } else if (s.recommendation.includes('Downsize')) {
                              recClass = 'rec-medium';
                            } else {
                              recClass = 'rec-low';
                            }

                            return (
                              <tr key={idx}>
                                <td><strong>{s.name}</strong></td>
                                <td>{s.contracted} desks</td>
                                <td>{s.actual_used} desks</td>
                                <td><span className="util-badge">{s.utilization_pct}</span></td>
                                <td><span className={`rec-badge ${recClass}`}>{s.recommendation}</span></td>
                              </tr>
                            );
                          })
                        ) : (
                          <tr>
                            <td colSpan="5" className="table-loading" style={{ textAlign: 'center', padding: '30px' }}>
                              No startup space utilization records found. Click "Add Startup" to get started.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Circular Average Occupancy Ratio Graph */}
                <div className="card dwell-card">
                  <div className="card-header">
                    <h2>Average Occupancy Ratio</h2>
                  </div>
                  <CircularOccupancyChart history={historyData} />
                </div>
              </div>
            </div>
          </section>
          )}
        </main>
      </div>

      {/* Startup Registry Popup Modal */}
      <AddStartupModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSuccess={fetchAnalytics}
      />
    </div>
  );
}
