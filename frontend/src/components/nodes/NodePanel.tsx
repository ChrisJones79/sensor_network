import NodeCard from './NodeCard';
import { NodeCard as NodeCardType } from '../../types';

interface Props {
  nodes: NodeCardType[];
  selectedNodeIds: string[];
  onToggleNode: (nodeId: string) => void;
  onRefresh: () => void;
}

export default function NodePanel({ nodes, selectedNodeIds, onToggleNode, onRefresh }: Props) {
  return (
    <section className="left-panel">
      <div className="left-panel-header">
        <h2>Nodes</h2>
        <button type="button" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      <div className="node-grid-scroll">
        <div className="node-grid">
          {nodes.map((node) => (
            <NodeCard
              key={node.node_id}
              node={node}
              selected={selectedNodeIds.includes(node.node_id)}
              onClick={() => onToggleNode(node.node_id)}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
