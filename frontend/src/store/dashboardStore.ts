import { useMemo, useState } from 'react';

export function useSelectedNodes(initial: string[] = []) {
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>(initial);

  function toggleNode(nodeId: string): void {
    setSelectedNodeIds((prev) => {
      if (prev.includes(nodeId)) {
        return prev.filter((id) => id !== nodeId);
      }
      return [...prev, nodeId];
    });
  }

  const selectedPrimary = useMemo(() => selectedNodeIds[0] ?? null, [selectedNodeIds]);

  return {
    selectedNodeIds,
    selectedPrimary,
    toggleNode,
    setSelectedNodeIds
  };
}
