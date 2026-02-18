import { useEffect, useMemo, useState } from 'react';

import { createOrUpdateConfig, sendCommand, updateNodeProfile, validateNodeConfig } from '../../api/client';
import { NodeCard } from '../../types';

interface SensorDraft {
  sid: string;
  stype: string;
  bus: number;
  pins: string;
  chans: string;
  period_ms: string;
}

interface CardLineDraft {
  line_index: number;
  source_type: 'channel' | 'token';
  source_ref: string;
  label: string;
}

interface Props {
  selectedNodeIds: string[];
  nodes: NodeCard[];
}

function defaultSensor(): SensorDraft {
  return {
    sid: '',
    stype: '',
    bus: 1,
    pins: '{"sda":21,"scl":22}',
    chans: '[{"cid":"temp","unit":"C"}]',
    period_ms: ''
  };
}

function defaultLines(): CardLineDraft[] {
  return [
    { line_index: 0, source_type: 'token', source_ref: 'status', label: 'Status' },
    { line_index: 1, source_type: 'token', source_ref: 'last_seen', label: 'Seen' },
    { line_index: 2, source_type: 'token', source_ref: 'age_s', label: 'Age' },
    { line_index: 3, source_type: 'token', source_ref: '', label: '' }
  ];
}

export default function CommissioningPanel({ selectedNodeIds, nodes }: Props) {
  const [nodeId, setNodeId] = useState('');
  const [cfgId, setCfgId] = useState(`cfg-${Date.now()}`);
  const [groups, setGroups] = useState('all');
  const [publishPeriodMs, setPublishPeriodMs] = useState(5000);
  const [sensorDrafts, setSensorDrafts] = useState<SensorDraft[]>([defaultSensor()]);
  const [advancedMode, setAdvancedMode] = useState(false);
  const [jsonText, setJsonText] = useState('');

  const [alias, setAlias] = useState('');
  const [location, setLocation] = useState('');
  const [cardColor, setCardColor] = useState('');
  const [cardLines, setCardLines] = useState<CardLineDraft[]>(defaultLines());

  const [result, setResult] = useState('');
  const [commandStatus, setCommandStatus] = useState('');

  const effectiveNodeId = useMemo(() => nodeId || selectedNodeIds[0] || '', [nodeId, selectedNodeIds]);

  useEffect(() => {
    if (!effectiveNodeId) {
      return;
    }
    const node = nodes.find((n) => n.node_id === effectiveNodeId);
    if (!node) {
      return;
    }
    setAlias(node.alias || '');
    setLocation(node.location || '');
    setCardColor(node.card_color_override || '');

    if (node.lines.length) {
      setCardLines(
        node.lines
          .slice(0, 4)
          .map((line, idx) => ({
            line_index: idx,
            source_type: line.source_type === 'channel' ? 'channel' : 'token',
            source_ref: line.source_ref,
            label: line.label
          }))
      );
    }
  }, [effectiveNodeId, nodes]);

  function buildGuidedPayload(): Record<string, unknown> {
    return {
      cfg_schema: 1,
      cfg_id: cfgId,
      applies_to: effectiveNodeId,
      groups: groups
        .split(',')
        .map((g) => g.trim())
        .filter(Boolean),
      defaults: {
        publish_period_ms: publishPeriodMs,
        max_batch_samples: 1,
        jitter_ms: 250,
        offline_cache: false
      },
      sensors: sensorDrafts.map((sensor) => ({
        sid: sensor.sid,
        stype: sensor.stype,
        bus: Number(sensor.bus),
        pins: JSON.parse(sensor.pins || '{}'),
        params: {},
        chans: JSON.parse(sensor.chans || '[]'),
        ...(sensor.period_ms ? { period_ms: Number(sensor.period_ms) } : {})
      }))
    };
  }

  function buildPayload(): Record<string, unknown> {
    if (advancedMode) {
      return JSON.parse(jsonText);
    }
    return buildGuidedPayload();
  }

  async function validateConfig(): Promise<void> {
    try {
      const payload = buildPayload();
      const out = await validateNodeConfig(effectiveNodeId, payload);
      setResult(out.valid ? 'Validation OK' : `Validation errors: ${out.errors.join('; ')}`);
    } catch (err) {
      setResult(`Validation failed: ${(err as Error).message}`);
    }
  }

  async function saveConfig(dispatch: boolean): Promise<void> {
    try {
      const payload = buildPayload();
      const out = await createOrUpdateConfig(payload, dispatch);
      setResult(`Config saved: ${JSON.stringify(out)}`);
    } catch (err) {
      setResult(`Save failed: ${(err as Error).message}`);
    }
  }

  async function saveNodeProfile(): Promise<void> {
    if (!effectiveNodeId) {
      setResult('Select or enter a node id first.');
      return;
    }
    try {
      const out = await updateNodeProfile(effectiveNodeId, {
        alias,
        location,
        card_color_override: cardColor,
        lines: cardLines
      });
      setResult(`Profile saved for ${out.node_id}`);
    } catch (err) {
      setResult(`Profile update failed: ${(err as Error).message}`);
    }
  }

  async function runCommand(op: 'READ_NOW' | 'SET_PERIOD' | 'REBOOT'): Promise<void> {
    if (!effectiveNodeId) {
      setCommandStatus('Select a node first.');
      return;
    }
    try {
      const args = op === 'SET_PERIOD' ? { period_ms: publishPeriodMs } : {};
      const out = await sendCommand(effectiveNodeId, op, args);
      setCommandStatus(`${op}: ${out.status} (${out.command_id})`);
    } catch (err) {
      setCommandStatus(`${op} failed: ${(err as Error).message}`);
    }
  }

  function patchSensor(idx: number, patch: Partial<SensorDraft>): void {
    setSensorDrafts((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  }

  function patchCardLine(idx: number, patch: Partial<CardLineDraft>): void {
    setCardLines((prev) => prev.map((line, i) => (i === idx ? { ...line, ...patch } : line)));
  }

  return (
    <section className="workspace-section">
      <div className="workspace-header">
        <h2>Commissioning</h2>
        <div className="workspace-actions">
          <button type="button" onClick={() => setAdvancedMode((v) => !v)}>
            {advancedMode ? 'Guided Form' : 'Advanced JSON'}
          </button>
        </div>
      </div>

      <div className="commission-grid">
        <label>
          Node ID
          <input value={effectiveNodeId} onChange={(e) => setNodeId(e.target.value)} placeholder="NID_..." />
        </label>
        <label>
          Config ID
          <input value={cfgId} onChange={(e) => setCfgId(e.target.value)} />
        </label>
        <label>
          Groups (csv)
          <input value={groups} onChange={(e) => setGroups(e.target.value)} />
        </label>
        <label>
          Publish Period (ms)
          <input type="number" value={publishPeriodMs} onChange={(e) => setPublishPeriodMs(Number(e.target.value))} />
        </label>
      </div>

      {advancedMode ? (
        <textarea
          className="advanced-json"
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
          placeholder='{"cfg_schema":1,...}'
        />
      ) : (
        <div className="sensor-editor">
          {sensorDrafts.map((sensor, idx) => (
            <div className="sensor-row" key={idx}>
              <input value={sensor.sid} onChange={(e) => patchSensor(idx, { sid: e.target.value })} placeholder="sid" />
              <input value={sensor.stype} onChange={(e) => patchSensor(idx, { stype: e.target.value })} placeholder="stype" />
              <input
                type="number"
                value={sensor.bus}
                onChange={(e) => patchSensor(idx, { bus: Number(e.target.value) })}
                placeholder="bus"
              />
              <input value={sensor.pins} onChange={(e) => patchSensor(idx, { pins: e.target.value })} placeholder="pins JSON" />
              <input value={sensor.chans} onChange={(e) => patchSensor(idx, { chans: e.target.value })} placeholder="chans JSON" />
              <input
                value={sensor.period_ms}
                onChange={(e) => patchSensor(idx, { period_ms: e.target.value })}
                placeholder="period_ms"
              />
            </div>
          ))}
          <button type="button" onClick={() => setSensorDrafts((prev) => [...prev, defaultSensor()])}>
            Add Sensor
          </button>
        </div>
      )}

      <div className="commission-actions">
        <button type="button" onClick={validateConfig}>
          Validate
        </button>
        <button type="button" onClick={() => saveConfig(false)}>
          Save Config
        </button>
        <button type="button" onClick={() => saveConfig(true)}>
          Save + SET_CONFIG
        </button>
      </div>

      <hr />
      <h3>Node Card Profile</h3>
      <div className="commission-grid">
        <label>
          Alias
          <input value={alias} onChange={(e) => setAlias(e.target.value)} />
        </label>
        <label>
          Location
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
        <label>
          Card Color (css)
          <input value={cardColor} onChange={(e) => setCardColor(e.target.value)} placeholder="optional" />
        </label>
      </div>
      <div className="sensor-editor">
        {cardLines.map((line, idx) => (
          <div className="sensor-row" key={line.line_index}>
            <input value={line.label} onChange={(e) => patchCardLine(idx, { label: e.target.value })} placeholder="label" />
            <select
              value={line.source_type}
              onChange={(e) => patchCardLine(idx, { source_type: e.target.value as 'channel' | 'token' })}
            >
              <option value="token">token</option>
              <option value="channel">channel</option>
            </select>
            <input
              value={line.source_ref}
              onChange={(e) => patchCardLine(idx, { source_ref: e.target.value })}
              placeholder="status | last_seen | age_s | sid.cid"
            />
          </div>
        ))}
      </div>
      <div className="commission-actions">
        <button type="button" onClick={saveNodeProfile}>
          Save Card Profile
        </button>
      </div>

      <hr />
      <div className="commission-actions">
        <button type="button" onClick={() => runCommand('READ_NOW')}>
          READ_NOW
        </button>
        <button type="button" onClick={() => runCommand('SET_PERIOD')}>
          SET_PERIOD
        </button>
        <button type="button" onClick={() => runCommand('REBOOT')}>
          REBOOT
        </button>
      </div>

      <pre className="panel-output">{result || 'No commissioning action yet.'}</pre>
      <pre className="panel-output">{commandStatus || 'No command sent yet.'}</pre>
    </section>
  );
}
