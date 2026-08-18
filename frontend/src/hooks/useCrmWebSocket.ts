"use client";

/**
 * Ensures the shared operator WebSocket is connected while the CRM Kanban
 * is mounted, so CRM_DEAL_* events update the board in real time.
 *
 * Reuses the same singleton socket as inbox (`useOperatorWebSocket`) —
 * no duplicate connections / listener leaks.
 */
export { useOperatorWebSocket as useCrmWebSocket } from "@/hooks/useOperatorWebSocket";
