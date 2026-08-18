/**
 * Lightweight dagre-style layered auto-layout (no native dagre dep required).
 * Positions nodes left→right by BFS rank from trigger/start nodes.
 */
import type { FlowCanvasEdge, FlowCanvasNode } from "@/types/flow";

const NODE_WIDTH = 260;
const NODE_HEIGHT = 140;
const RANK_GAP_X = 320;
const RANK_GAP_Y = 180;

export function autoLayoutGraph(
  nodes: FlowCanvasNode[],
  edges: FlowCanvasEdge[],
): FlowCanvasNode[] {
  if (nodes.length === 0) return nodes;

  const ids = new Set(nodes.map((n) => n.id));
  const outgoing = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  for (const n of nodes) {
    outgoing.set(n.id, []);
    indegree.set(n.id, 0);
  }
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    outgoing.get(e.source)!.push(e.target);
    indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1);
  }

  const roots = nodes
    .filter((n) => n.type === "trigger" || (indegree.get(n.id) ?? 0) === 0)
    .map((n) => n.id);
  const start = roots.length > 0 ? roots : [nodes[0].id];

  const rank = new Map<string, number>();
  const queue = [...start];
  for (const id of start) rank.set(id, 0);

  while (queue.length > 0) {
    const cur = queue.shift()!;
    const r = rank.get(cur) ?? 0;
    for (const next of outgoing.get(cur) ?? []) {
      const proposed = r + 1;
      if (!rank.has(next) || (rank.get(next) ?? 0) < proposed) {
        rank.set(next, proposed);
        queue.push(next);
      }
    }
  }

  // Unvisited (disconnected) nodes get trailing ranks
  let maxRank = 0;
  for (const n of nodes) {
    if (!rank.has(n.id)) {
      maxRank += 1;
      rank.set(n.id, maxRank);
    } else {
      maxRank = Math.max(maxRank, rank.get(n.id)!);
    }
  }

  const buckets = new Map<number, string[]>();
  for (const n of nodes) {
    const r = rank.get(n.id) ?? 0;
    const list = buckets.get(r) ?? [];
    list.push(n.id);
    buckets.set(r, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [r, bucket] of Array.from(buckets.entries())) {
    bucket.forEach((id: string, index: number) => {
      positions.set(id, {
        x: 80 + r * RANK_GAP_X,
        y: 80 + index * RANK_GAP_Y - ((bucket.length - 1) * RANK_GAP_Y) / 2,
      });
    });
  }

  return nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) ?? node.position,
    // Hint for future dagre swap — dimensions used by ranking gaps
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
  }));
}
