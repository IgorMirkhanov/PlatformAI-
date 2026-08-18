"use client";

import { Table2 } from "lucide-react";
import { Position, type NodeProps } from "reactflow";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import type { GoogleSheetsAction, GoogleSheetsNodeData } from "@/types/flow";

const ACTION_LABELS: Record<GoogleSheetsAction, string> = {
  append_row: "Append row",
  read_row: "Read row",
};

function truncateSpreadsheetId(id: string, maxLength = 14): string {
  const trimmed = id.trim();
  if (!trimmed) {
    return "Not configured";
  }
  if (trimmed.length <= maxLength) {
    return trimmed;
  }
  return `${trimmed.slice(0, maxLength)}…`;
}

export function GoogleSheetsNode({
  id,
  data,
  selected,
}: NodeProps<GoogleSheetsNodeData>) {
  const spreadsheetPreview = truncateSpreadsheetId(data.spreadsheet_id);
  const actionLabel = ACTION_LABELS[data.action];

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-emerald-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-emerald-500/20"
        title="Google Sheets"
        subtitle={data.label || "Spreadsheet integration"}
        widthClass="w-[340px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <Table2 className="h-4 w-4 text-emerald-300" />
          </div>
        }
      >
        <div>
          <label className={flowLabelClassName}>Action</label>
          <div className={`${flowFieldClassName} text-zinc-300`}>{actionLabel}</div>
        </div>

        <div>
          <label className={flowLabelClassName}>Spreadsheet ID</label>
          <div
            className={`${flowFieldClassName} truncate font-mono text-xs text-zinc-300`}
            title={data.spreadsheet_id || undefined}
          >
            {spreadsheetPreview}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={flowLabelClassName}>Sheet</label>
            <div className={`${flowFieldClassName} truncate text-zinc-300`}>
              {data.sheet_name || "Sheet1"}
            </div>
          </div>
          <div>
            <label className={flowLabelClassName}>Columns</label>
            <div className={`${flowFieldClassName} text-zinc-300`}>
              {data.column_mappings.length}
            </div>
          </div>
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-emerald-500"
      />
    </FlowNodeWrapper>
  );
}
