"use client";

import { Handle } from "reactflow";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

type FlowHandleProps = ComponentProps<typeof Handle>;

export function FlowHandle({ className, ...props }: FlowHandleProps) {
  return (
    <Handle
      {...props}
      className={cn(
        "!h-3 !w-3 !border-2 !border-zinc-900 transition-all duration-150",
        "hover:!h-[14px] hover:!w-[14px] hover:!-translate-x-0 hover:!shadow-[0_0_10px_rgba(139,92,246,0.45)]",
        className,
      )}
    />
  );
}
