"use client";

import {
  Bot,
  Building2,
  Database,
  FileSearch,
  GitBranch,
  Globe2,
  ImageIcon,
  MessageCircle,
  MessageSquare,
  Table2,
  Webhook,
  Zap,
} from "lucide-react";
import type { DragEvent } from "react";

import { cn } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import { NODE_PALETTE_ITEMS, type CanvasNodeType } from "@/types/flow";

const NODE_ICONS: Partial<Record<CanvasNodeType, typeof MessageSquare>> = {
  trigger: Zap,
  textMessage: MessageSquare,
  whatsapp: MessageCircle,
  condition: GitBranch,
  aiAgent: Bot,
  llm: Bot,
  knowledgeSearch: FileSearch,
  rag: FileSearch,
  apiRequest: Globe2,
  crmAction: Webhook,
  crm: Building2,
  googleSheets: Table2,
  sqlQuery: Database,
  imageGeneration: ImageIcon,
};

const NODE_COLORS: Partial<Record<CanvasNodeType, string>> = {
  trigger: "text-sky-300 bg-sky-500/10 border-sky-500/20",
  textMessage: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
  whatsapp: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
  condition: "text-amber-300 bg-amber-500/10 border-amber-500/20",
  aiAgent: "text-violet-300 bg-violet-500/10 border-violet-500/20",
  llm: "text-violet-300 bg-violet-500/10 border-violet-500/20",
  knowledgeSearch: "text-teal-300 bg-teal-500/10 border-teal-500/20",
  rag: "text-teal-300 bg-teal-500/10 border-teal-500/20",
  apiRequest: "text-cyan-300 bg-cyan-500/10 border-cyan-500/20",
  crmAction: "text-indigo-300 bg-indigo-500/10 border-indigo-500/20",
  crm: "text-indigo-300 bg-indigo-500/10 border-indigo-500/20",
  googleSheets: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
  sqlQuery: "text-sky-300 bg-sky-500/10 border-sky-500/20",
  imageGeneration: "text-fuchsia-300 bg-fuchsia-500/10 border-fuchsia-500/20",
};

interface NodePaletteProps {
  className?: string;
}

export function NodePalette({ className }: NodePaletteProps) {
  const addNode = useFlowStore((state) => state.addNode);

  const handleDragStart = (
    event: DragEvent<HTMLButtonElement>,
    type: CanvasNodeType,
  ): void => {
    event.dataTransfer.setData("application/reactflow", type);
    event.dataTransfer.effectAllowed = "move";
  };

  const handleClick = (type: CanvasNodeType): void => {
    addNode(type);
  };

  return (
    <aside
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95 backdrop-blur-sm",
        className,
      )}
    >
      <div className="border-b border-zinc-800 px-4 py-4">
        <h2 className="text-sm font-semibold text-zinc-100">Node Palette</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Drag or click to add enterprise flow blocks
        </p>
      </div>

      <div className="flex flex-col gap-2 p-3">
        {NODE_PALETTE_ITEMS.map((item) => {
          const Icon = NODE_ICONS[item.type] ?? MessageSquare;

          return (
            <button
              key={item.type}
              type="button"
              draggable
              onDragStart={(event) => handleDragStart(event, item.type)}
              onClick={() => handleClick(item.type)}
              className={cn(
                "group flex w-full cursor-grab items-start gap-3 rounded-xl border p-3 text-left transition-all",
                "border-zinc-800 bg-zinc-950/70 hover:border-zinc-700 hover:bg-zinc-900 active:cursor-grabbing",
              )}
            >
              <div
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border",
                  NODE_COLORS[item.type],
                )}
              >
                <Icon className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-medium text-zinc-100">{item.label}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                  {item.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-auto border-t border-zinc-800 p-4">
        <p className="text-[11px] leading-relaxed text-zinc-600">
          Branch handles map to{" "}
          <code className="rounded bg-zinc-950 px-1 text-zinc-400">sourceHandle</code>{" "}
          in exported JSON. Condition uses <code className="text-zinc-400">true/false</code>,
          API Request uses <code className="text-zinc-400">success/failure</code>.
        </p>
      </div>
    </aside>
  );
}
