"use client";

import { Settings2, Trash2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { stopFlowKeyboardPropagation } from "@/components/flow/nodes/LocalNodeField";
import { SqlQueryNodeConfig } from "@/components/flow/nodes/SqlQueryNodeConfig";
import { LLMNodeConfig } from "@/components/flow/nodes/LLMNodeConfig";
import { ImageGenerationNodeConfig } from "@/components/flow/nodes/ImageGenerationNodeConfig";
import { useFlowStore } from "@/store/useFlowStore";
import {
  isAIAgentData,
  isApiRequestData,
  isConditionData,
  isCRMActionData,
  isGoogleSheetsData,
  isHumanHandoffData,
  isImageGenerationData,
  isKnowledgeSearchData,
  isLoopData,
  isSqlQueryData,
  isTextMessageData,
  isTriggerData,
  isWhatsAppData,
  type FlowNodeData,
  type GoogleSheetsColumnMapping,
} from "@/types/flow";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-zinc-600";
const textareaClass = `${inputClass} min-h-[88px] resize-y`;
const fieldKeyProps = {
  onKeyDown: stopFlowKeyboardPropagation,
  onKeyUp: stopFlowKeyboardPropagation,
} as const;

export function PropertiesPanel({ className }: { className?: string }) {
  const selectedNode = useFlowStore((s) => s.selectedNode);
  const updateNodeData = useFlowStore((s) => s.updateNodeData);
  const deleteNode = useFlowStore((s) => s.deleteNode);
  const setSelectedNode = useFlowStore((s) => s.setSelectedNode);
  const nodes = useFlowStore((s) => s.nodes);

  // Keep panel in sync with live node data after edits
  const live = selectedNode
    ? nodes.find((n) => n.id === selectedNode.id) ?? selectedNode
    : null;

  if (!live) {
    return (
      <aside
        className={cn(
          "flex w-80 shrink-0 flex-col rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95",
          className,
        )}
      >
        <div className="border-b border-zinc-800 px-4 py-4">
          <h2 className="text-sm font-semibold text-zinc-100">Properties</h2>
          <p className="mt-1 text-xs text-zinc-500">Select a node on the canvas</p>
        </div>
        <div className="flex flex-1 items-center justify-center p-6 text-center text-xs text-zinc-600">
          No node selected
        </div>
      </aside>
    );
  }

  const data = live.data as FlowNodeData;
  const patch = (partial: Partial<FlowNodeData>) => updateNodeData(live.id, partial);

  return (
    <aside
      className={cn(
        "flex w-80 shrink-0 flex-col overflow-hidden rounded-2xl border border-zinc-800/90 bg-[#0d0d0f]/95",
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-zinc-400" />
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Properties</h2>
            <p className="text-[11px] text-zinc-500">
              {live.type} · {live.id.slice(0, 8)}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setSelectedNode(null)}
          className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300"
          aria-label="Close properties"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div
        className="flex flex-1 flex-col gap-4 overflow-y-auto p-4"
        onKeyDown={stopFlowKeyboardPropagation}
        onKeyUp={stopFlowKeyboardPropagation}
      >
        <Field label="Label">
          <input
            className={inputClass}
            value={"label" in data ? String(data.label ?? "") : ""}
            onChange={(e) => patch({ label: e.target.value } as Partial<FlowNodeData>)}
            {...fieldKeyProps}
          />
        </Field>

        {isTriggerData(data) && (
          <>
            <Field label="Trigger type">
              <select
                className={inputClass}
                value={data.trigger_type}
                onChange={(e) =>
                  patch({ trigger_type: e.target.value as typeof data.trigger_type })
                }
              >
                <option value="message_received">Message received</option>
                <option value="webhook">Webhook</option>
                <option value="manual">Manual</option>
              </select>
            </Field>
            <Field label="Webhook event">
              <input
                className={inputClass}
                value={data.webhook_event}
                onChange={(e) => patch({ webhook_event: e.target.value })}
              />
            </Field>
          </>
        )}

        {(isTextMessageData(data) || isWhatsAppData(data)) && (
          <Field label="Message text">
            <textarea
              className={textareaClass}
              value={data.text}
              onChange={(e) => patch({ text: e.target.value })}
            />
          </Field>
        )}

        {isWhatsAppData(data) && (
          <Field label="Media URL">
            <input
              className={inputClass}
              value={data.media_url ?? ""}
              onChange={(e) => patch({ media_url: e.target.value })}
            />
          </Field>
        )}

        {isAIAgentData(data) && (
          <>
            <LLMNodeConfig
              variant="panel"
              textareaClassName={textareaClass}
              selectClassName={inputClass}
              promptValue={data.prompt_context}
              modelName={data.model_name}
              onPromptChange={(value) => patch({ prompt_context: value })}
              onModelChange={(model_name) => patch({ model_name })}
              botTask={data.label}
              rows={6}
            />
            <Field label="Temperature">
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                className={inputClass}
                value={data.temperature ?? 0.7}
                onChange={(e) => patch({ temperature: Number(e.target.value) })}
              />
            </Field>
          </>
        )}

        {isConditionData(data) && (
          <>
            <Field label="Condition type">
              <select
                className={inputClass}
                value={data.condition_type}
                onChange={(e) =>
                  patch({ condition_type: e.target.value as typeof data.condition_type })
                }
              >
                <option value="customer_tag">Customer tag</option>
                <option value="working_hours">Working hours</option>
                <option value="expression">Expression</option>
              </select>
            </Field>
            <Field label="Tag / Expression">
              <input
                className={inputClass}
                value={data.condition_type === "expression" ? data.expression : data.tag}
                onChange={(e) =>
                  patch(
                    data.condition_type === "expression"
                      ? { expression: e.target.value }
                      : { tag: e.target.value },
                  )
                }
              />
            </Field>
          </>
        )}

        {isKnowledgeSearchData(data) && (
          <>
            <Field label="Top K">
              <input
                type="number"
                min={1}
                max={20}
                className={inputClass}
                value={data.top_k}
                onChange={(e) => patch({ top_k: Number(e.target.value) })}
              />
            </Field>
            <Field label="Query variable">
              <input
                className={inputClass}
                value={data.query_variable}
                onChange={(e) => patch({ query_variable: e.target.value })}
              />
            </Field>
            <Field label="Output variable">
              <input
                className={inputClass}
                value={data.output_variable}
                onChange={(e) => patch({ output_variable: e.target.value })}
              />
            </Field>
          </>
        )}

        {isApiRequestData(data) && (
          <>
            <Field label="Method">
              <select
                className={inputClass}
                value={data.method}
                onChange={(e) => patch({ method: e.target.value as typeof data.method })}
              >
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
            </Field>
            <Field label="URL">
              <input
                className={inputClass}
                value={data.url}
                onChange={(e) => patch({ url: e.target.value })}
              />
            </Field>
            <Field label="Body template">
              <textarea
                className={textareaClass}
                value={data.body_template}
                onChange={(e) => patch({ body_template: e.target.value })}
              />
            </Field>
          </>
        )}

        {isCRMActionData(data) && (
          <>
            <Field label="Integration">
              <select
                className={inputClass}
                value={data.integration_type}
                onChange={(e) =>
                  patch({
                    integration_type: e.target.value as typeof data.integration_type,
                  })
                }
              >
                <option value="custom_webhook">Custom webhook</option>
                <option value="amocrm">amoCRM</option>
                <option value="bitrix24">Bitrix24</option>
              </select>
            </Field>
            <Field label="URL">
              <input
                className={inputClass}
                value={data.url}
                onChange={(e) => patch({ url: e.target.value })}
              />
            </Field>
            <Field label="Body template">
              <textarea
                className={textareaClass}
                value={data.body_template}
                onChange={(e) => patch({ body_template: e.target.value })}
              />
            </Field>
          </>
        )}

        {isLoopData(data) && (
          <>
            <Field label="Max iterations">
              <input
                type="number"
                min={1}
                max={100}
                className={inputClass}
                value={data.max_iterations}
                onChange={(e) =>
                  patch({ max_iterations: Math.max(1, Number(e.target.value) || 1) })
                }
              />
            </Field>
            <Field label="Continue expression">
              <input
                className={inputClass}
                value={data.continue_expression}
                onChange={(e) => patch({ continue_expression: e.target.value })}
              />
            </Field>
          </>
        )}

        {isHumanHandoffData(data) && (
          <>
            <Field label="Handoff message">
              <textarea
                className={textareaClass}
                value={data.handoff_message}
                onChange={(e) => patch({ handoff_message: e.target.value })}
              />
            </Field>
            <Field label="Queue tag">
              <input
                className={inputClass}
                value={data.queue_tag}
                onChange={(e) => patch({ queue_tag: e.target.value })}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm text-zinc-300">
              <input
                type="checkbox"
                checked={data.pause_bot}
                onChange={(e) => patch({ pause_bot: e.target.checked })}
              />
              Pause bot until operator resumes
            </label>
          </>
        )}

        {isGoogleSheetsData(data) && (
          <>
            <Field label="Spreadsheet ID">
              <input
                className={inputClass}
                placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
                value={data.spreadsheet_id}
                onChange={(e) => patch({ spreadsheet_id: e.target.value })}
                {...fieldKeyProps}
              />
            </Field>
            <Field label="Sheet name">
              <input
                className={inputClass}
                placeholder="Sheet1"
                value={data.sheet_name}
                onChange={(e) => patch({ sheet_name: e.target.value })}
                {...fieldKeyProps}
              />
            </Field>
            <Field label="Action">
              <select
                className={inputClass}
                value={data.action}
                onChange={(e) =>
                  patch({ action: e.target.value as typeof data.action })
                }
              >
                <option value="append_row">Append row</option>
                <option value="read_row">Read row</option>
              </select>
            </Field>

            {data.action === "read_row" && (
              <>
                <Field label="Filter column">
                  <input
                    className={inputClass}
                    placeholder="A"
                    value={data.filter_column}
                    onChange={(e) => patch({ filter_column: e.target.value })}
                    {...fieldKeyProps}
                  />
                </Field>
                <Field label="Filter value">
                  <input
                    className={inputClass}
                    placeholder="{{user_phone}}"
                    value={data.filter_value}
                    onChange={(e) => patch({ filter_value: e.target.value })}
                    {...fieldKeyProps}
                  />
                </Field>
                <Field label="Result variable">
                  <input
                    className={inputClass}
                    placeholder="sheet_result"
                    value={data.result_variable}
                    onChange={(e) => patch({ result_variable: e.target.value })}
                    {...fieldKeyProps}
                  />
                </Field>
              </>
            )}

            <div className="flex flex-col gap-2">
              <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                Column mappings
              </span>
              <p className="text-[11px] text-zinc-600">
                {data.action === "append_row"
                  ? "Column key → session variable to read from"
                  : "Column key → session variable to write into"}
              </p>
              {data.column_mappings.map((mapping, idx) => (
                <div key={idx} className="flex items-center gap-1.5">
                  <input
                    className={`${inputClass} flex-1`}
                    placeholder="Column"
                    value={mapping.column_key}
                    onChange={(e) => {
                      const updated = data.column_mappings.map((m, i) =>
                        i === idx ? { ...m, column_key: e.target.value } : m,
                      );
                      patch({ column_mappings: updated } as Partial<FlowNodeData>);
                    }}
                    {...fieldKeyProps}
                  />
                  <span className="text-zinc-600">↔</span>
                  <input
                    className={`${inputClass} flex-1`}
                    placeholder="Variable"
                    value={mapping.variable_name}
                    onChange={(e) => {
                      const updated = data.column_mappings.map((m, i) =>
                        i === idx ? { ...m, variable_name: e.target.value } : m,
                      );
                      patch({ column_mappings: updated } as Partial<FlowNodeData>);
                    }}
                    {...fieldKeyProps}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      patch({
                        column_mappings: data.column_mappings.filter((_, i) => i !== idx),
                      } as Partial<FlowNodeData>);
                    }}
                    className="rounded p-1 text-zinc-500 hover:text-red-400"
                    aria-label="Remove mapping"
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => {
                  const newMapping: GoogleSheetsColumnMapping = {
                    column_key: "",
                    variable_name: "",
                  };
                  patch({
                    column_mappings: [...data.column_mappings, newMapping],
                  } as Partial<FlowNodeData>);
                }}
                className="mt-1 rounded-md border border-dashed border-zinc-700 px-3 py-1.5 text-xs text-zinc-500 hover:border-zinc-500 hover:text-zinc-300"
              >
                + Add mapping
              </button>
            </div>
          </>
        )}

        {isSqlQueryData(data) && <SqlQueryNodeConfig data={data} patch={patch} />}
        {isImageGenerationData(data) && (
          <ImageGenerationNodeConfig data={data} patch={patch} />
        )}
      </div>

      <div className="border-t border-zinc-800 p-3">
        <button
          type="button"
          onClick={() => {
            deleteNode(live.id);
            setSelectedNode(null);
          }}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300 hover:bg-red-500/20"
        >
          <Trash2 className="h-4 w-4" />
          Delete node
        </button>
      </div>
    </aside>
  );
}
