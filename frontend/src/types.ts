export type StatusState = 'green' | 'yellow' | 'red' | 'unknown';

export interface NodeCardLineValue {
  line_index: number;
  label: string;
  value: string;
  source_type: string;
  source_ref: string;
  ts: string | null;
}

export interface NodeStatus {
  state: StatusState;
  intensity: number;
  age_seconds: number | null;
  last_seen: string | null;
}

export interface NodeCard {
  node_id: string;
  alias: string;
  location: string;
  card_color_override: string;
  status: NodeStatus;
  lines: NodeCardLineValue[];
}

export interface ChannelDescriptor {
  node_id: string;
  sid: string;
  cid: string;
  unit: string;
  latest_value: number | boolean | string | null;
  latest_ts: string | null;
}

export interface TraceSelector {
  node_id: string;
  sid: string;
  cid: string;
  label: string;
}

export interface PlotConfig {
  plot_id: string;
  title: string;
  y_axis_label: string;
  live_mode: boolean;
  traces: TraceSelector[];
  options: Record<string, unknown>;
}

export interface DashboardPlotConfig {
  plots: PlotConfig[];
}

export interface TracePoint {
  ts: string;
  value: number | boolean | string | null;
}

export interface TraceSeries {
  node_id: string;
  sid: string;
  cid: string;
  label: string;
  points: TracePoint[];
}

export interface TelemetryQueryResponse {
  traces: TraceSeries[];
}

export interface CommandResponse {
  command_id: string;
  node_id: string;
  op: string;
  status: 'pending' | 'ok' | 'fail' | 'timeout';
  issued_ts: string;
  timeout_ts: string;
  ack_ts: string | null;
  ack_detail: string | null;
  ack_rc: number | null;
}

export interface DBStats {
  db_path: string;
  db_size_bytes: number;
  table_counts: Record<string, number>;
  latest_timestamps: Record<string, string | null>;
}
