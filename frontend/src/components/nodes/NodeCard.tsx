import { NodeCard as NodeCardType } from '../../types';

interface Props {
  node: NodeCardType;
  selected: boolean;
  onClick: () => void;
}

function statusRgb(state: string): [number, number, number] {
  if (state === 'green') {
    return [54, 179, 126];
  }
  if (state === 'yellow') {
    return [228, 184, 67];
  }
  if (state === 'red') {
    return [208, 74, 74];
  }
  return [131, 143, 160];
}

export default function NodeCard({ node, selected, onClick }: Props) {
  const [r, g, b] = statusRgb(node.status.state);
  const alpha = Math.max(0.3, Math.min(1, node.status.intensity));
  const border = `rgba(${r}, ${g}, ${b}, ${alpha})`;
  const fill = node.card_color_override || `rgba(${r}, ${g}, ${b}, ${Math.max(0.18, alpha * 0.38)})`;

  return (
    <button
      className={`node-card ${selected ? 'selected' : ''}`}
      onClick={onClick}
      style={{ borderColor: border, background: fill }}
      type="button"
    >
      <header className="node-card-header">
        <strong>{node.alias || node.node_id}</strong>
        <span className="node-card-status">{node.status.state.toUpperCase()}</span>
      </header>

      <div className="node-card-subtitle">{node.location || node.node_id}</div>

      <div className="node-card-lines">
        {node.lines.map((line) => (
          <div key={`${node.node_id}-${line.line_index}`} className="node-line">
            <span>{line.label || `L${line.line_index + 1}`}</span>
            <span>{line.value}</span>
            <small>{line.ts ? new Date(line.ts).toLocaleTimeString() : '--:--:--'}</small>
          </div>
        ))}
      </div>
    </button>
  );
}
