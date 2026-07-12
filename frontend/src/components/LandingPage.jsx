import React, { useState } from 'react';

export default function LandingPage({ onLaunchDemo }) {
  const [activeFeatureTab, setActiveFeatureTab] = useState('meeting');

  const featureTabs = [
    {
      id: 'meeting',
      label: 'Meeting Room',
      title: 'Auto-Release Ghost Bookings',
      desc: 'Computer vision algorithms detect anonymous presence in meeting rooms. If a reserved room remains vacant for 10 minutes, the room booking system auto-releases it to maintain high workspace availability.'
    },
    {
      id: 'office',
      label: 'Open Office',
      title: 'Optimize Flexible Desking',
      desc: 'Analyze hot-desking usage rates across open plan floors. Track actual utilization trends to reduce desk ratios, reallocate clusters, and align space with actual demand.'
    },
    {
      id: 'planning',
      label: 'Workplace Planning',
      title: 'Data-Driven Downsizing',
      desc: 'Compare contract allocations against actual daily attendance. Use occupancy logs to negotiate space sizing and lease renewals with empirical metrics rather than guesswork.'
    },
    {
      id: 'automation',
      label: 'Building Automation',
      title: 'Smart HVAC & Lighting Integration',
      desc: 'Link real-time occupancy counts directly to building automation systems. Dynamically throttle air handling units and switch off lighting in vacant building wings to save power.'
    }
  ];

  const currentTabContent = featureTabs.find(t => t.id === activeFeatureTab);

  return (
    <div className="landing-layout">
      {/* Navigation Header */}
      <nav className="landing-nav">
        <div className="landing-nav-container">
          <div className="landing-brand">
            <div className="logo-box"></div>
            <span className="landing-brand-name">OccuSense AI</span>
          </div>
          
          <div className="landing-nav-links">
            <span className="active">Computer Vision</span>
            <span>Solutions</span>
            <span>Success Stories</span>
            <span>Resources</span>
            <span>Company</span>
          </div>

          <button className="btn btn-primary" onClick={onLaunchDemo}>
            Online Demo
          </button>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="landing-hero">
        <div className="landing-container hero-grid">
          <div className="hero-content">
            <span className="hero-badge">AI-Powered Computer Vision</span>
            <h1 className="hero-title">OccuSense AI Workplace Occupancy Detection</h1>
            <p className="hero-description">
              Real-world success with workplace occupancy detection. Deployed in modern corporate spaces, 
              this advanced computer vision system provides Jio with real-time floor utilization visibility, enabling yield management and flexible desking products.
            </p>
            <div style={{ marginTop: '32px' }}>
              <button className="btn btn-primary btn-lg" onClick={onLaunchDemo}>
                Try Online Live Demo
              </button>
            </div>
          </div>
          <div className="hero-visual">
            <img 
              src="/static/images/vs121_sensor.png" 
              alt="OccuSense AI Ceiling Device" 
              className="hero-sensor-img"
            />
          </div>
        </div>
      </section>

      {/* The Real Business Problem Section */}
      <section className="landing-solutions">
        <div className="landing-container">
          <div style={{ textAlign: 'center', marginBottom: '48px' }}>
            <span className="hero-badge">The Business Model</span>
            <h2 className="section-title">The Real Business Problem in Shared Workspaces</h2>
            <p className="section-subtitle">
              Why Jio needs actual occupancy data: shifting from rigid contracts to dynamic yield management.
            </p>
          </div>

          <div className="solutions-grid">
            <div className="solution-card">
              <div className="solution-icon">📊</div>
              <h4>1. Actual Usage Mismatch</h4>
              <p className="problem"><strong>The Issue:</strong> Jio sells 15 seats to Startup A because that is what they said they need. However, Startup A consistently uses only 8 seats. Startup A pays for 7 wasted seats, and Jio misses the opportunity to sell that capacity to someone else.</p>
              <p className="solve"><strong>How We Solve It:</strong> Real occupancy data allows Jio to have constructive conversations during contract renewal—offering Startup A a rightsized 10-seat package at a savings, while releasing the freed capacity to onboard new startups.</p>
            </div>
            
            <div className="solution-card">
              <div className="solution-icon">💳</div>
              <h4>2. Rigid Seat Pricing Limitations</h4>
              <p className="problem"><strong>The Issue:</strong> Shared workspaces currently only offer fixed seat allocations ("15 seats, yours forever"). Flexible desking packages cannot be priced or managed without continuous occupancy tracking.</p>
              <p className="solve"><strong>How We Solve It:</strong> Accurate presence data becomes the foundation for dynamic pricing products: "Pay for 10 guaranteed desks + access to 5 flexible seats when available," maximizing customer choice and Jio's floor yield.</p>
            </div>

            <div className="solution-card">
              <div className="solution-icon">✈️</div>
              <h4>3. Floor Capacity Planning (Yield Management)</h4>
              <p className="problem"><strong>The Issue:</strong> If a floor has 100 seats, Jio sells exactly 100 seats. However, historical peak usage on the floor never exceeds 70 seats at any given time, leaving 30% of paid space idle.</p>
              <p className="solve"><strong>How We Solve It:</strong> Just like airlines and hotels, Jio can safely oversell floor capacity (e.g., selling 120 seat contracts on a 100-seat floor) or repurpose the 30 consistently empty desks into premium meeting rooms or lounge areas.</p>
            </div>

            <div className="solution-card">
              <div className="solution-icon">🔒</div>
              <h4>4. Employee Privacy Regulations</h4>
              <p className="problem"><strong>The Issue:</strong> Standard CCTV surveillance and facial recognition violate employee privacy regulations (GDPR/CCPA) and trigger security concerns.</p>
              <p className="solve"><strong>How We Solve It:</strong> Images decode, infer, and annotate inside local volatile RAM, immediately purging frames. No facial data or personal identifiers (PI) write to the database, ensuring absolute privacy compliance.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Revised Business Value Table */}
      <section className="landing-metrics" style={{ background: '#ffffff', borderBottom: '1px solid var(--border)' }}>
        <div className="landing-container">
          <div style={{ textAlign: 'center', marginBottom: '40px' }}>
            <h2 className="section-title">Data-Driven Decisions: We Detect, You Decide</h2>
            <p className="section-subtitle">
              How OccuSense AI transforms raw visual frames into concrete business optimizations.
            </p>
          </div>

          <div className="table-card" style={{ maxWidth: '900px', margin: '0 auto', boxShadow: '0 4px 20px rgba(0,0,0,0.03)' }}>
            <div className="table-wrapper">
              <table className="report-table">
                <thead>
                  <tr>
                    <th style={{ width: '45%' }}>What We Detect</th>
                    <th style={{ width: '55%' }}>Business Decision It Enables</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><strong>Startup A uses 10 of 15 desks daily on average</strong></td>
                    <td><span className="util-badge">Rightsize Renewals</span> Offer a 10-seat package at renewal, saving them money and freeing up space for new clients.</td>
                  </tr>
                  <tr>
                    <td><strong>Peak usage across a 100-seat floor is 70 seats</strong></td>
                    <td><span className="util-badge">Yield Management</span> Safely onboard 2 more startups without expanding physical desk counts (overselling).</td>
                  </tr>
                  <tr>
                    <td><strong>Startup B uses 100% of their allocated seats daily</strong></td>
                    <td><span className="util-badge">Expansion Upsell</span> Proactively pitch more desks or a larger dedicated office space.</td>
                  </tr>
                  <tr>
                    <td><strong>Floor occupancy drops below 5% every Friday</strong></td>
                    <td><span className="util-badge">Operational Savings</span> Close early, shut down HVAC units, and turn off lighting to cut costs.</td>
                  </tr>
                  <tr>
                    <td><strong>Daily occupancy peaks between 10:00 AM and 2:00 PM</strong></td>
                    <td><span className="util-badge">Maintenance Planning</span> Schedule floor cleaning and device maintenance outside of peak hours.</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      {/* Reframe for Interview Banner */}
      <section className="landing-metrics" style={{ background: '#f8fafc' }}>
        <div className="landing-container" style={{ maxWidth: '900px' }}>
          <div className="business-quote-box">
            <h4>💡 Executive Product Pitch</h4>
            <blockquote className="business-blockquote">
              "The system provides Jio with real occupancy data versus contracted allocation. This enables data-driven decisions at contract renewal, helps design flexible pricing products, and gives Jio visibility into true floor utilization for capacity planning — without violating existing contractual agreements."
            </blockquote>
            <p className="business-quote-author">— OccuSense AI Product Strategy</p>
          </div>
        </div>
      </section>

      {/* How We Solve it through CV Section */}
      <section className="landing-features" style={{ background: '#ffffff' }}>
        <div className="landing-container">
          <div style={{ textAlign: 'center', marginBottom: '48px' }}>
            <h2 className="section-title">How We Solve This Through Computer Vision</h2>
            <p className="section-subtitle">
              Custom overhead spatial intelligence algorithms designed to deliver reliable occupancy counting.
            </p>
          </div>

          <div className="metrics-grid">
            <div className="metric-card">
              <div className="metric-num">🚶‍♂️</div>
              <h4>Perspective Aisle Gate</h4>
              <p>Filters out pedestrians walking through aisles or in front of desks using relative Y-coordinate thresholds, preventing walking traffic from triggering false occupancy states.</p>
            </div>
            <div className="metric-card">
              <div className="metric-num">⏳</div>
              <h4>State Hysteresis Filter</h4>
              <p>Stabilizes posture detection: locking a seat occupied requires 3 positive frames, while releasing it to vacant requires 15 consecutive frames (2.5s delay) to absorb shifting posture.</p>
            </div>
            <div className="metric-card">
              <div className="metric-num">📐</div>
              <h4>Projection Distance Scaling</h4>
              <p>Overcomes ceiling camera perspective compression by scaling allowed matching gates proportionally to desk box sizes, stopping background actors from triggering foreground chairs.</p>
            </div>
          </div>

          {/* Feature Tabs section */}
          <div className="feature-tabs" style={{ marginTop: '64px' }}>
            {featureTabs.map(tab => (
              <button
                key={tab.id}
                className={`tab-toggle ${activeFeatureTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveFeatureTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="feature-showcase-card">
            <div className="showcase-visual">
              <img 
                src="/static/images/office_workplace.png" 
                alt="Smart Office Layout" 
                className="showcase-office-img"
              />
            </div>
            <div className="showcase-content">
              <h3>{currentTabContent.title}</h3>
              <p>{currentTabContent.desc}</p>
              <div style={{ marginTop: '24px' }}>
                <button className="btn btn-secondary" onClick={onLaunchDemo}>
                  Launch Interactive Demo &rarr;
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-container">
          <p>&copy; 2026 OccuSense AI. All rights reserved. Deployed for advanced yield management and shared capacity planning.</p>
        </div>
      </footer>
    </div>
  );
}
