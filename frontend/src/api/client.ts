import axios from 'axios';
import {
  ChannelDescriptor,
  CommandResponse,
  DashboardPlotConfig,
  DBStats,
  NodeCard,
  TelemetryQueryResponse,
  TraceSelector
} from '../types';

const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const api = axios.create({
  baseURL: apiBase
});

export async function fetchNodes(): Promise<NodeCard[]> {
  const { data } = await api.get<NodeCard[]>('/api/nodes');
  return data;
}

export async function updateNodeProfile(
  nodeId: string,
  payload: {
    alias?: string;
    location?: string;
    card_color_override?: string;
    lines?: Array<{
      line_index: number;
      source_type: 'channel' | 'token';
      source_ref: string;
      label: string;
    }>;
  }
): Promise<NodeCard> {
  const { data } = await api.patch<NodeCard>(`/api/nodes/${nodeId}/profile`, payload);
  return data;
}

export async function fetchNodeChannels(nodeId: string): Promise<ChannelDescriptor[]> {
  const { data } = await api.get<ChannelDescriptor[]>(`/api/nodes/${nodeId}/channels`);
  return data;
}

export async function fetchPlotConfig(): Promise<DashboardPlotConfig> {
  const { data } = await api.get<DashboardPlotConfig>('/api/plots/config');
  return data;
}

export async function savePlotConfig(config: DashboardPlotConfig): Promise<DashboardPlotConfig> {
  const { data } = await api.post<DashboardPlotConfig>('/api/plots/config', config);
  return data;
}

export async function queryTelemetry(traces: TraceSelector[], startTs: string, endTs: string): Promise<TelemetryQueryResponse> {
  const { data } = await api.post<TelemetryQueryResponse>('/api/telemetry/query', {
    traces,
    start_ts: startTs,
    end_ts: endTs,
    max_points_per_trace: 5000
  });
  return data;
}

export async function sendCommand(nodeId: string, op: string, args: Record<string, unknown> = {}, targetSid: string | null = null): Promise<CommandResponse> {
  const { data } = await api.post<CommandResponse>('/api/commands', {
    node_id: nodeId,
    op,
    args,
    target_sid: targetSid
  });
  return data;
}

export async function getCommand(commandId: string): Promise<CommandResponse> {
  const { data } = await api.get<CommandResponse>(`/api/commands/${commandId}`);
  return data;
}

export async function validateNodeConfig(nodeId: string, config: Record<string, unknown>): Promise<{ valid: boolean; errors: string[] }> {
  const { data } = await api.post('/api/commissioning/node/' + nodeId + '/validate', {
    source: 'dashboard',
    config,
    dispatch_set_config: false
  });
  return data;
}

export async function createOrUpdateConfig(config: Record<string, unknown>, dispatchSetConfig: boolean): Promise<Record<string, unknown>> {
  const { data } = await api.post('/api/commissioning/node', {
    source: 'dashboard',
    config,
    dispatch_set_config: dispatchSetConfig
  });
  return data;
}

export async function fetchDbStats(): Promise<DBStats> {
  const { data } = await api.get<DBStats>('/api/db/stats');
  return data;
}

export async function exportDb(table: string, format: 'json' | 'csv', limit: number): Promise<Record<string, unknown>> {
  const { data } = await api.post('/api/db/export', { table, format, limit });
  return data;
}

export async function pruneDb(table: string, olderThan: string): Promise<Record<string, unknown>> {
  const { data } = await api.post('/api/db/prune', { table, older_than: olderThan });
  return data;
}

export function liveWsUrl(): string {
  const u = new URL(apiBase);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = '/ws/live';
  return u.toString();
}
