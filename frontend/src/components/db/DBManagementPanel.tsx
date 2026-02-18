import { useEffect, useState } from 'react';

import { exportDb, fetchDbStats, pruneDb } from '../../api/client';
import { DBStats } from '../../types';

const tableOptions = [
  'nodes',
  'node_card_lines',
  'node_configs',
  'inventory_snapshots',
  'telemetry_frames_raw',
  'channel_samples',
  'command_log',
  'ack_log',
  'dashboard_plot_configs'
];

const pruneOptions = ['channel_samples', 'telemetry_frames_raw', 'inventory_snapshots', 'ack_log', 'command_log'];

export default function DBManagementPanel() {
  const [stats, setStats] = useState<DBStats | null>(null);
  const [table, setTable] = useState('channel_samples');
  const [format, setFormat] = useState<'json' | 'csv'>('json');
  const [limit, setLimit] = useState(200);
  const [pruneTable, setPruneTable] = useState('channel_samples');
  const [olderThan, setOlderThan] = useState('');
  const [output, setOutput] = useState('');

  async function refreshStats(): Promise<void> {
    try {
      const data = await fetchDbStats();
      setStats(data);
    } catch (err) {
      setOutput(`Failed to fetch stats: ${(err as Error).message}`);
    }
  }

  useEffect(() => {
    void refreshStats();
  }, []);

  async function runExport(): Promise<void> {
    try {
      const data = await exportDb(table, format, limit);
      setOutput(JSON.stringify(data, null, 2));
    } catch (err) {
      setOutput(`Export failed: ${(err as Error).message}`);
    }
  }

  async function runPrune(): Promise<void> {
    if (!olderThan) {
      setOutput('older_than is required for prune.');
      return;
    }
    try {
      const data = await pruneDb(pruneTable, new Date(olderThan).toISOString());
      setOutput(JSON.stringify(data, null, 2));
      await refreshStats();
    } catch (err) {
      setOutput(`Prune failed: ${(err as Error).message}`);
    }
  }

  return (
    <section className="workspace-section">
      <div className="workspace-header">
        <h2>Database Management</h2>
        <div className="workspace-actions">
          <button type="button" onClick={refreshStats}>
            Refresh Stats
          </button>
        </div>
      </div>

      {stats && (
        <div className="db-stats">
          <div>
            <strong>DB:</strong> {stats.db_path}
          </div>
          <div>
            <strong>Size:</strong> {stats.db_size_bytes.toLocaleString()} bytes
          </div>
          <div className="db-counts">
            {Object.entries(stats.table_counts).map(([name, count]) => (
              <span key={name}>
                {name}: {count}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="db-actions-row">
        <label>
          Export Table
          <select value={table} onChange={(e) => setTable(e.target.value)}>
            {tableOptions.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <label>
          Format
          <select value={format} onChange={(e) => setFormat(e.target.value as 'json' | 'csv')}>
            <option value="json">json</option>
            <option value="csv">csv</option>
          </select>
        </label>
        <label>
          Limit
          <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
        </label>
        <button type="button" onClick={runExport}>
          Export
        </button>
      </div>

      <div className="db-actions-row">
        <label>
          Prune Table
          <select value={pruneTable} onChange={(e) => setPruneTable(e.target.value)}>
            {pruneOptions.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <label>
          Older Than
          <input type="datetime-local" value={olderThan} onChange={(e) => setOlderThan(e.target.value)} />
        </label>
        <button type="button" onClick={runPrune}>
          Prune
        </button>
      </div>

      <pre className="panel-output">{output || 'DB output will appear here.'}</pre>
    </section>
  );
}
