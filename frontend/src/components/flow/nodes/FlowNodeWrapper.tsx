"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";

interface FlowNodeWrapperProps {
  nodeId: string;
  selected?: boolean;
  children: ReactNode;
  className?: string;
}

export function FlowNodeWrapper({
  nodeId,
  selected,
  children,
  className,
}: FlowNodeWrapperProps) {
  const deleteNode = useFlowStore((state) => state.deleteNode);
  const isInvalid = useFlowStore((state) => state.invalidNodeIds.includes(nodeId));

  return (
    <div
      className={cn(
        "group/node relative",
        selected && "is-selected",
        isInvalid && "is-invalid",
        className,
      )}
      data-invalid={isInvalid || undefined}
    >
      <button
        type="button"
        aria-label="Удалить узел"
        onClick={(event) => {
          event.stopPropagation();
          deleteNode(nodeId);
        }}
        className={cn(
          "nodrag absolute -right-2 -top-2 z-20 flex h-6 w-6 items-center justify-center rounded-full",
          "border border-zinc-700/80 bg-zinc-950/95 text-zinc-400 opacity-0 shadow-md",
          "transition-all duration-150 group-hover/node:opacity-100",
          "hover:border-red-500/40 hover:bg-red-950/80 hover:text-red-300",
          selected && "opacity-100",
        )}
      >
        <X className="h-3 w-3" />
      </button>
      {children}
    </div>
  );
}
