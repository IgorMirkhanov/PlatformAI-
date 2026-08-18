"use client";

import { useCallback } from "react";
import { Position, type NodeProps } from "reactflow";
import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowLabelClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import {
  LocalNodeInput,
  LocalNodeTextarea,
} from "@/components/flow/nodes/LocalNodeField";
import { generateId } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import type { FlowButton, TextMessageNodeData } from "@/types/flow";

export function TextMessageNode({
  id,
  data,
  selected,
}: NodeProps<TextMessageNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  const commitText = useCallback(
    (text: string) => {
      updateNodeData(id, { text });
    },
    [id, updateNodeData],
  );

  const handleAddButton = (): void => {
    const newButton: FlowButton = {
      id: generateId("btn"),
      text: `Button ${data.buttons.length + 1}`,
    };
    updateNodeData(id, { buttons: [...data.buttons, newButton] });
  };

  const handleRemoveButton = (buttonId: string): void => {
    updateNodeData(id, {
      buttons: data.buttons.filter((button) => button.id !== buttonId),
    });
  };

  const hasButtons = data.buttons.length > 0;

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
        title="Text Message"
        subtitle={data.label}
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <MessageSquare className="h-4 w-4 text-emerald-300" />
          </div>
        }
        footer={
          hasButtons ? (
            <>
              {data.buttons.map((button, index) => (
                <FlowHandle
                  key={button.id}
                  type="source"
                  position={Position.Bottom}
                  id={button.id}
                  style={{
                    left: `${((index + 1) / (data.buttons.length + 1)) * 100}%`,
                  }}
                  className="!bg-violet-500"
                />
              ))}
              <div className="border-t border-zinc-800/90 px-4 pb-3 pt-2 text-center text-[10px] uppercase tracking-wider text-zinc-600">
                {data.buttons.length} button output{data.buttons.length !== 1 ? "s" : ""}
              </div>
            </>
          ) : (
            <FlowHandle
              type="source"
              position={Position.Right}
              id="default"
              className="!-right-1.5 !top-1/2 !bg-violet-500"
            />
          )
        }
      >
        <div>
          <label htmlFor={`${id}-text`} className={flowLabelClassName}>
            Bot response
          </label>
          <LocalNodeTextarea
            id={`${id}-text`}
            externalValue={data.text}
            onCommit={commitText}
            placeholder="Type the message your bot will send directly on canvas…"
            rows={5}
            className="min-h-[120px]"
          />
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className={flowLabelClassName}>Inline reply buttons</span>
            <button
              type="button"
              onClick={handleAddButton}
              className="nodrag flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-violet-300 hover:bg-violet-500/10"
            >
              <Plus className="h-3 w-3" />
              Add
            </button>
          </div>

          {data.buttons.length === 0 ? (
            <p className="rounded-xl border border-dashed border-zinc-800 px-3 py-2 text-xs text-zinc-500">
              No buttons — connect via the right handle
            </p>
          ) : (
            <ul className="space-y-2">
              {data.buttons.map((button, index) => (
                <li key={button.id} className="relative flex items-center gap-2">
                  <LocalNodeInput
                    type="text"
                    externalValue={button.text}
                    onCommit={(text) =>
                      updateNodeData(id, {
                        buttons: data.buttons.map((item) =>
                          item.id === button.id ? { ...item, text } : item,
                        ),
                      })
                    }
                    placeholder="Button label"
                    className="flex-1"
                  />
                  <button
                    type="button"
                    onClick={() => handleRemoveButton(button.id)}
                    className="nodrag rounded-md p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-400"
                    aria-label={`Remove button ${index + 1}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </FlowNodeShell>
    </FlowNodeWrapper>
  );
}
