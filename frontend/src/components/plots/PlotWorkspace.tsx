import { useEffect, useMemo, useState } from 'react';
import Plot from 'react-plotly.js';

import { fetchNodeChannels, fetchPlotConfig, queryTelemetry, savePlotConfig } from '../../api/client';
import { ChannelDescriptor, DashboardPlotConfig, PlotConfig, TraceSeries } from '../../types';

interface Props {
  selectedNodeIds: string[];
  liveTick: number;
}

function mkPlot(index: number): PlotConfig {
  return {
    plot_id: `plot-${index + 1}`,
    title: `Plot ${index + 1}`,
    y_axis_label: '',
    live_mode: true,
    traces: [],
    options: {
      range_minutes: 10
    }
  };
}

function channelKey(ch: ChannelDescriptor): string {
  return `${ch.node_id}|${ch.sid}|${ch.cid}`;
}

function optionString(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
}

export default function PlotWorkspace({ selectedNodeIds, liveTick }: Props) {
  const [config, setConfig] = useState<DashboardPlotConfig>({ plots: [mkPlot(0)] });
  const [seriesByPlot, setSeriesByPlot] = useState<Record<string, TraceSeries[]>>({});
  const [channels, setChannels] = useState<ChannelDescriptor[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchPlotConfig()
      .then((cfg) => setConfig(cfg))
      .catch(() => setConfig({ plots: [mkPlot(0)] }));
  }, []);

  useEffect(() => {
    if (selectedNodeIds.length === 0) {
      setChannels([]);
      return;
    }
    Promise.all(selectedNodeIds.map((nodeId) => fetchNodeChannels(nodeId).catch(() => []))).then((chunks) => {
      setChannels(chunks.flat());
    });
  }, [selectedNodeIds]);

  const channelOptions = useMemo(
    () =>
      channels.map((ch) => ({
        key: channelKey(ch),
        label: `${ch.node_id} · ${ch.sid}.${ch.cid} (${ch.unit || '-'})`,
        channel: ch
      })),
    [channels]
  );

  async function reloadPlotData(activeConfig: DashboardPlotConfig): Promise<void> {
    setLoading(true);
    const next: Record<string, TraceSeries[]> = {};
    const now = new Date();

    for (const plot of activeConfig.plots) {
      if (plot.traces.length === 0) {
        next[plot.plot_id] = [];
        continue;
      }

      const rangeMinutes = Number(plot.options.range_minutes ?? 10);
      const defaultStart = new Date(now.getTime() - rangeMinutes * 60_000).toISOString();
      const defaultEnd = now.toISOString();
      const startTs = plot.live_mode
        ? defaultStart
        : optionString(plot.options.start_ts, defaultStart);
      const endTs = plot.live_mode
        ? defaultEnd
        : optionString(plot.options.end_ts, defaultEnd);

      try {
        const resp = await queryTelemetry(plot.traces, startTs, endTs);
        next[plot.plot_id] = resp.traces;
      } catch {
        next[plot.plot_id] = [];
      }
    }

    setSeriesByPlot(next);
    setLoading(false);
  }

  useEffect(() => {
    reloadPlotData(config);
    const interval = window.setInterval(() => {
      const hasLive = config.plots.some((p) => p.live_mode);
      if (hasLive) {
        reloadPlotData(config);
      }
    }, 5000);

    return () => window.clearInterval(interval);
  }, [config, liveTick]);

  async function persist(next: DashboardPlotConfig): Promise<void> {
    setConfig(next);
    try {
      await savePlotConfig(next);
    } catch {
      // Keep local state even if save fails.
    }
  }

  function updatePlot(plotId: string, patch: Partial<PlotConfig>): void {
    const next = {
      plots: config.plots.map((p) => (p.plot_id === plotId ? { ...p, ...patch } : p))
    };
    void persist(next);
  }

  function updateOptions(plotId: string, key: string, value: unknown): void {
    const next = {
      plots: config.plots.map((p) =>
        p.plot_id === plotId ? { ...p, options: { ...p.options, [key]: value } } : p
      )
    };
    void persist(next);
  }

  function addPlot(): void {
    if (config.plots.length >= 3) {
      return;
    }
    const next = { plots: [...config.plots, mkPlot(config.plots.length)] };
    void persist(next);
  }

  function removePlot(plotId: string): void {
    if (config.plots.length <= 1) {
      return;
    }
    const next = { plots: config.plots.filter((p) => p.plot_id !== plotId) };
    void persist(next);
  }

  function addTrace(plotId: string, optionKey: string): void {
    const choice = channelOptions.find((opt) => opt.key === optionKey);
    if (!choice) {
      return;
    }

    const trace = {
      node_id: choice.channel.node_id,
      sid: choice.channel.sid,
      cid: choice.channel.cid,
      label: `${choice.channel.node_id}:${choice.channel.sid}.${choice.channel.cid}`
    };

    const next = {
      plots: config.plots.map((p) =>
        p.plot_id === plotId ? { ...p, traces: [...p.traces, trace] } : p
      )
    };
    void persist(next);
  }

  function removeTrace(plotId: string, idx: number): void {
    const next = {
      plots: config.plots.map((p) =>
        p.plot_id === plotId
          ? {
              ...p,
              traces: p.traces.filter((_, i) => i !== idx)
            }
          : p
      )
    };
    void persist(next);
  }

  return (
    <section className="workspace-section">
      <div className="workspace-header">
        <h2>Time Domain Plots</h2>
        <div className="workspace-actions">
          <button type="button" onClick={addPlot} disabled={config.plots.length >= 3}>
            Add Plot
          </button>
          <button type="button" onClick={() => reloadPlotData(config)}>
            Refresh Data
          </button>
        </div>
      </div>

      <div className="plot-list">
        {config.plots.map((plot) => {
          const traces = seriesByPlot[plot.plot_id] ?? [];
          return (
            <article className="plot-card" key={plot.plot_id}>
              <div className="plot-controls">
                <input
                  value={plot.title}
                  onChange={(e) => updatePlot(plot.plot_id, { title: e.target.value })}
                  placeholder="Plot title"
                />
                <input
                  value={plot.y_axis_label}
                  onChange={(e) => updatePlot(plot.plot_id, { y_axis_label: e.target.value })}
                  placeholder="Y axis label"
                />
                <label>
                  <input
                    type="checkbox"
                    checked={plot.live_mode}
                    onChange={(e) => updatePlot(plot.plot_id, { live_mode: e.target.checked })}
                  />
                  Live
                </label>
                <button type="button" onClick={() => removePlot(plot.plot_id)} disabled={config.plots.length === 1}>
                  Remove
                </button>
              </div>

              {!plot.live_mode ? (
                <div className="plot-time-range">
                  <input
                    type="datetime-local"
                    value={optionString(plot.options.start_ts, '').slice(0, 16)}
                    onChange={(e) => updateOptions(plot.plot_id, 'start_ts', new Date(e.target.value).toISOString())}
                  />
                  <input
                    type="datetime-local"
                    value={optionString(plot.options.end_ts, '').slice(0, 16)}
                    onChange={(e) => updateOptions(plot.plot_id, 'end_ts', new Date(e.target.value).toISOString())}
                  />
                </div>
              ) : (
                <div className="plot-time-range">
                  <label>
                    Range (min)
                    <input
                      type="number"
                      min={1}
                      max={1440}
                      value={Number(plot.options.range_minutes ?? 10)}
                      onChange={(e) => updateOptions(plot.plot_id, 'range_minutes', Number(e.target.value))}
                    />
                  </label>
                </div>
              )}

              <div className="plot-trace-editor">
                <select defaultValue="" onChange={(e) => addTrace(plot.plot_id, e.target.value)}>
                  <option value="">Add trace from selected nodes...</option>
                  {channelOptions.map((opt) => (
                    <option key={opt.key} value={opt.key}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <div className="trace-tags">
                  {plot.traces.map((trace, idx) => (
                    <button key={`${trace.node_id}-${trace.sid}-${trace.cid}-${idx}`} type="button" onClick={() => removeTrace(plot.plot_id, idx)}>
                      {trace.label} ×
                    </button>
                  ))}
                </div>
              </div>

              <Plot
                data={traces.map((series) => ({
                  x: series.points.map((point) => point.ts),
                  y: series.points.map((point) => {
                    if (typeof point.value === 'boolean') {
                      return point.value ? 1 : 0;
                    }
                    return point.value;
                  }),
                  type: 'scatter',
                  mode: 'lines',
                  name: series.label
                }))}
                layout={{
                  title: plot.title,
                  paper_bgcolor: '#f5f7ef',
                  plot_bgcolor: '#ffffff',
                  margin: { l: 42, r: 16, t: 42, b: 38 },
                  yaxis: {
                    title: plot.y_axis_label
                  },
                  legend: {
                    orientation: 'h'
                  }
                }}
                style={{ width: '100%', height: '320px' }}
                useResizeHandler
                config={{ responsive: true, displaylogo: false }}
              />
            </article>
          );
        })}
      </div>

      <div className="workspace-footer">{loading ? 'Loading plot data...' : 'Ready'}</div>
    </section>
  );
}
