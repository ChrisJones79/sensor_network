import { useEffect, useState } from 'react';

import { fetchNodes, liveWsUrl } from './api/client';
import CommissioningPanel from './components/commissioning/CommissioningPanel';
import DBManagementPanel from './components/db/DBManagementPanel';
import NodePanel from './components/nodes/NodePanel';
import PlotWorkspace from './components/plots/PlotWorkspace';
import DashboardLayout from './layout/DashboardLayout';
import { useSelectedNodes } from './store/dashboardStore';
import { NodeCard } from './types';

type RightTab = 'plots' | 'commissioning' | 'db';

export default function App() {
  const [nodes, setNodes] = useState<NodeCard[]>([]);
  const [tab, setTab] = useState<RightTab>('plots');
  const [liveTick, setLiveTick] = useState(0);
  const [connection, setConnection] = useState('disconnected');
  const { selectedNodeIds, toggleNode } = useSelectedNodes();

  async function refreshNodes(): Promise<void> {
    try {
      const data = await fetchNodes();
      setNodes(data);
    } catch {
      // Keep previous data if refresh fails.
    }
  }

  useEffect(() => {
    void refreshNodes();
    const interval = window.setInterval(() => {
      void refreshNodes();
    }, 10000);

    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const ws = new WebSocket(liveWsUrl());
    ws.onopen = () => setConnection('connected');
    ws.onclose = () => setConnection('disconnected');
    ws.onmessage = (evt) => {
      try {
        const message = JSON.parse(evt.data);
        if (message.type === 'telemetry' || message.type === 'inventory' || message.type === 'command') {
          setLiveTick((v) => v + 1);
          void refreshNodes();
        }
      } catch {
        // Ignore non-json payloads.
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  return (
    <DashboardLayout
      left={
        <NodePanel
          nodes={nodes}
          selectedNodeIds={selectedNodeIds}
          onToggleNode={toggleNode}
          onRefresh={() => void refreshNodes()}
        />
      }
      right={
        <>
          <header className="right-header">
            <h1>Isolated Sensor Network Dashboard</h1>
            <div className="header-status">WS: {connection}</div>
            <nav className="right-tabs">
              <button type="button" className={tab === 'plots' ? 'active' : ''} onClick={() => setTab('plots')}>
                Plots
              </button>
              <button
                type="button"
                className={tab === 'commissioning' ? 'active' : ''}
                onClick={() => setTab('commissioning')}
              >
                Commissioning
              </button>
              <button type="button" className={tab === 'db' ? 'active' : ''} onClick={() => setTab('db')}>
                DB Management
              </button>
            </nav>
          </header>

          {tab === 'plots' && <PlotWorkspace selectedNodeIds={selectedNodeIds} liveTick={liveTick} />}
          {tab === 'commissioning' && <CommissioningPanel selectedNodeIds={selectedNodeIds} nodes={nodes} />}
          {tab === 'db' && <DBManagementPanel />}
        </>
      }
    />
  );
}
