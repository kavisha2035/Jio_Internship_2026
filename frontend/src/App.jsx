import React, { useState, useEffect, useRef } from 'react';
import LandingPage from './components/LandingPage';
import Dashboard from './components/Dashboard';

export default function App() {
  const [view, setView] = useState('landing');
  const [cameraData, setCameraData] = useState({});
  const [connectionStatus, setConnectionStatus] = useState('Disconnected');
  const [frameCount, setFrameCount] = useState(0);
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const wsDelayRef = useRef(1500);

  const connectWS = () => {
    if (wsRef.current) return;

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host || 'localhost:8000';
    const url = `${proto}://${host}/ws/live?camera_id=cam_floor2`;
    
    console.log(`[React-WS] Connecting to ${url}`);
    setConnectionStatus('Connecting...');
    
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[React-WS] Connected successfully.');
      setConnectionStatus('Connected');
      wsDelayRef.current = 1500;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'frame') {
          setCameraData(msg);
          setFrameCount(prev => prev + 1);
        }
      } catch (err) {
        console.error('[React-WS] Parse error:', err);
      }
    };

    ws.onclose = () => {
      console.log('[React-WS] Connection closed.');
      setConnectionStatus('Reconnecting...');
      wsRef.current = null;
      scheduleReconnect();
    };

    ws.onerror = (err) => {
      console.error('[React-WS] Error encountered:', err);
      ws.close();
    };
  };

  const scheduleReconnect = () => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = setTimeout(() => {
      wsDelayRef.current = Math.min(wsDelayRef.current * 1.5, 15000);
      connectWS();
    }, wsDelayRef.current);
  };

  const disconnectWS = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    setConnectionStatus('Disconnected');
  };

  // Start/stop websocket connection depending on the active view
  useEffect(() => {
    if (view === 'dashboard') {
      connectWS();
      setFrameCount(0);
    } else {
      disconnectWS();
    }
    return () => disconnectWS();
  }, [view]);

  return (
    <React.Fragment>
      {view === 'landing' ? (
        <LandingPage onLaunchDemo={() => setView('dashboard')} />
      ) : (
        <Dashboard
          cameraData={cameraData}
          connectionStatus={connectionStatus}
          frameCount={frameCount}
          onBackToProduct={() => setView('landing')}
        />
      )}
    </React.Fragment>
  );
}
