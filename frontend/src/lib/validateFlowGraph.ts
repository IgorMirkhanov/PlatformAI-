/**
 * Flow graph structural validation (pre-publish / pre-test).
 */

import type { Connection } from "reactflow";

import {
  isApiRequestData,
  isConditionData,
  isTextMessageData,
  isValidFlowConnection,
  type FlowCanvasEdge,
  type FlowCanvasNode,
} from "@/types/flow";

export interface GraphValidationIssue {
  code: string;
  message: string;
  nodeId?: string;
  edgeId?: string;
  buttonId?: string;
}

export interface FlowGraphValidationResult {
  ok: boolean;
  issues: GraphValidationIssue[];
  invalidNodeIds: string[];
}

function collectInvalidIds(issues: GraphValidationIssue[]): string[] {
  return Array.from(
    new Set(issues.map((issue) => issue.nodeId).filter((id): id is string => Boolean(id))),
  );
}

/**
 * Validate canvas topology before Test / Publish.
 */
export function validateFlowGraph(
  nodes: FlowCanvasNode[],
  edges: FlowCanvasEdge[],
): FlowGraphValidationResult {
  const issues: GraphValidationIssue[] = [];

  if (nodes.length === 0) {
    issues.push({
      code: "empty_canvas",
      message: "Добавьте хотя бы один блок перед запуском.",
    });
    return { ok: false, issues, invalidNodeIds: [] };
  }

  const nodeIds = new Set(nodes.map((node) => node.id));
  const incoming = new Set(edges.map((edge) => edge.target));
  const outgoing = new Set(edges.map((edge) => edge.source));

  // Entry / Start: prefer explicit trigger; otherwise any node without incoming edges.
  const triggerNodes = nodes.filter((node) => node.type === "trigger");
  if (triggerNodes.length === 0) {
    const entryCandidates = nodes.filter((node) => !incoming.has(node.id));
    if (entryCandidates.length === 0) {
      issues.push({
        code: "missing_start",
        message: "Нужна точка входа: добавьте блок Trigger (Start).",
      });
    }
  }

  // Disconnected nodes (no in and no out), excluding lone trigger on empty draft.
  for (const node of nodes) {
    const hasIn = incoming.has(node.id);
    const hasOut = outgoing.has(node.id);
    if (!hasIn && !hasOut && nodes.length > 1) {
      issues.push({
        code: "disconnected_node",
        message: `Блок «${node.data?.label || node.type}» не связан с графом.`,
        nodeId: node.id,
      });
    }
  }

  // Orphan edges / invalid endpoints
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      issues.push({
        code: "orphan_edge",
        message: `Связь «${edge.id}» указывает на отсутствующий блок.`,
        edgeId: edge.id,
        nodeId: nodeIds.has(edge.source) ? edge.target : edge.source,
      });
      continue;
    }

    const probe: Connection = {
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    };
    // Self-loop / duplicate checks against peers excluding this edge.
    const peers = edges.filter((item) => item.id !== edge.id);
    if (!isValidFlowConnection(probe, peers)) {
      issues.push({
        code: "invalid_connection",
        message: "Некорректный тип связи между блоками.",
        edgeId: edge.id,
        nodeId: edge.source,
      });
    }
  }

  // Branch integrity
  for (const node of nodes) {
    if (node.type === "condition" && isConditionData(node.data)) {
      for (const handle of ["true", "false"] as const) {
        const connected = edges.some(
          (edge) => edge.source === node.id && edge.sourceHandle === handle,
        );
        if (!connected) {
          issues.push({
            code: "condition_branch_unconnected",
            message: "Подключите обе ветки у логического блока Condition.",
            nodeId: node.id,
            buttonId: handle,
          });
          break;
        }
      }
    }

    if (node.type === "apiRequest" && isApiRequestData(node.data)) {
      for (const handle of ["success", "failure"] as const) {
        const connected = edges.some(
          (edge) => edge.source === node.id && edge.sourceHandle === handle,
        );
        if (!connected) {
          issues.push({
            code: "api_request_outcome_unconnected",
            message: "Подключите оба исхода у блока API Request.",
            nodeId: node.id,
            buttonId: handle,
          });
          break;
        }
      }
    }

    if (
      (node.type === "textMessage" || node.type === "whatsapp") &&
      isTextMessageData(node.data)
    ) {
      for (const button of node.data.buttons) {
        const hasEdge = edges.some(
          (edge) => edge.source === node.id && edge.sourceHandle === button.id,
        );
        if (!hasEdge) {
          issues.push({
            code: "button_without_target",
            message: `Кнопка «${button.text}» не подключена.`,
            nodeId: node.id,
            buttonId: button.id,
          });
        }
      }
    }
  }

  const invalidNodeIds = collectInvalidIds(issues);
  return {
    ok: issues.length === 0,
    issues,
    invalidNodeIds,
  };
}
