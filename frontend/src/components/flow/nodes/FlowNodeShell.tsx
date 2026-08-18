"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FlowNodeShellProps {
  selected?: boolean;
  accentClass?: string;
  icon: ReactNode;
  title: string;
  subtitle: string;
  widthClass?: string;
  children: ReactNode;
  footer?: ReactNode;
}

export function FlowNodeShell({
  selected,
  accentClass = "border-zinc-800",
  icon,
  title,
  subtitle,
  widthClass = "w-[340px]",
  children,
  footer,
}: FlowNodeShellProps) {
  return (
    <div
      className={cn(
        widthClass,
        "overflow-hidden rounded-2xl border bg-[#0d0d0f]/95 shadow-node backdrop-blur-sm transition-all duration-200",
        "group-data-[invalid]/node:border-red-500/55 group-data-[invalid]/node:ring-2 group-data-[invalid]/node:ring-red-500/35",
        selected
          ? "border-violet-500/60 shadow-[0_0_15px_rgba(139,92,246,0.15)] ring-1 ring-violet-500/25 group-data-[invalid]/node:shadow-none"
          : cn(
              accentClass,
              "group-hover/node:border-zinc-600 group-hover/node:shadow-[0_0_15px_rgba(139,92,246,0.15)]",
            ),
      )}
    >
      <div className="flex items-center gap-2 border-b border-zinc-800/90 bg-zinc-950/60 px-4 py-3">
        {icon}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
            {title}
          </p>
          <p className="text-sm font-semibold text-zinc-100">{subtitle}</p>
        </div>
      </div>
      <div className="space-y-4 p-4">{children}</div>
      {footer}
    </div>
  );
}

export const flowFieldClassName =
  "nodrag nowheel w-full rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/50 focus:outline-none focus:ring-2 focus:ring-violet-500/15";

export const flowTextareaClassName =
  "nodrag nowheel w-full resize-none rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-2.5 font-mono text-[13px] leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/50 focus:outline-none focus:ring-2 focus:ring-violet-500/15";

export const flowLabelClassName = "mb-1.5 block text-xs font-medium text-zinc-400";
