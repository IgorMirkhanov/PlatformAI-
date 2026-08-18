"use client";

import { useCallback, useEffect } from "react";

import { useFlowStore } from "@/store/useFlowStore";

/**
 * Bind Ctrl/Cmd+Z and Ctrl+Y / Cmd+Shift+Z to flow undo/redo.
 */
export function useFlowHistoryHotkeys(enabled = true): void {
  const undo = useFlowStore((state) => state.undo);
  const redo = useFlowStore((state) => state.redo);

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (!enabled) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }

      const meta = event.metaKey || event.ctrlKey;
      if (!meta) return;

      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
        return;
      }
      if (key === "y" || (key === "z" && event.shiftKey)) {
        event.preventDefault();
        redo();
      }
    },
    [enabled, redo, undo],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onKeyDown]);
}
