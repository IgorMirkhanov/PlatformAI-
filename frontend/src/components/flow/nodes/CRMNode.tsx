"use client";

import { Position, type NodeProps } from "reactflow";
import { Braces, Building2, Plus, Trash2, Webhook } from "lucide-react";

import { FlowHandle } from "@/components/flow/nodes/FlowHandle";
import {
  flowFieldClassName,
  flowLabelClassName,
  flowTextareaClassName,
  FlowNodeShell,
} from "@/components/flow/nodes/FlowNodeShell";
import { FlowNodeWrapper } from "@/components/flow/nodes/FlowNodeWrapper";
import { cn, generateId } from "@/lib/utils";
import { useFlowStore } from "@/store/useFlowStore";
import type {
  CRMActionNodeData,
  CRMHeaderPair,
  CRMHttpMethod,
  CRMIntegrationType,
} from "@/types/crm";

const INTEGRATION_OPTIONS: Array<{ value: CRMIntegrationType; label: string }> = [
  { value: "custom_webhook", label: "Custom Webhook" },
  { value: "amocrm", label: "amoCRM" },
  { value: "bitrix24", label: "Bitrix24" },
];

const METHOD_OPTIONS: CRMHttpMethod[] = ["POST", "GET", "PUT"];

const VARIABLE_CHIPS = [
  "{{message}}",
  "{{phone}}",
  "{{user_name}}",
  "{{channel}}",
  "{{rag_context}}",
] as const;

/**
 * CRM Action / Custom Webhook node — mid-flow HTTP calls with response mapping.
 * Registered as canvas type ``crmAction`` → backend ``crm_action``.
 */
export function CrmNode({ id, data, selected }: NodeProps<CRMActionNodeData>) {
  const updateNodeData = useFlowStore((state) => state.updateNodeData);

  const integration = (data.integration_type ||
    data.action_type ||
    "custom_webhook") as CRMIntegrationType;

  const patch = (next: Partial<CRMActionNodeData>): void => {
    const nextIntegration = (next.integration_type ??
      data.integration_type ??
      "custom_webhook") as CRMIntegrationType;
    const platform =
      nextIntegration === "amocrm" || nextIntegration === "bitrix24"
        ? nextIntegration
        : data.platform === "bitrix24"
          ? "bitrix24"
          : "amocrm";

    updateNodeData(id, {
      ...next,
      integration_type: nextIntegration,
      action_type: nextIntegration,
      platform,
      params: {
        ...data.params,
        platform,
        pipeline_id: data.pipeline_id,
        stage_id: data.stage_id,
        tags: data.params?.tags ?? [],
      },
    });
  };

  const updateHeader = (headerId: string, field: "key" | "value", value: string): void => {
    const headers = (data.headers ?? []).map((header) =>
      header.id === headerId ? { ...header, [field]: value } : header,
    );
    patch({ headers });
  };

  const addHeader = (): void => {
    const headers: CRMHeaderPair[] = [
      ...(data.headers ?? []),
      { id: generateId("hdr"), key: "", value: "" },
    ];
    patch({ headers });
  };

  const removeHeader = (headerId: string): void => {
    const headers = (data.headers ?? []).filter((header) => header.id !== headerId);
    patch({
      headers:
        headers.length > 0
          ? headers
          : [{ id: generateId("hdr"), key: "Content-Type", value: "application/json" }],
    });
  };

  const insertVariable = (token: string): void => {
    const next = data.url ? `${data.url.trimEnd()}${token}` : token;
    patch({ url: next });
  };

  return (
    <FlowNodeWrapper nodeId={id} selected={selected}>
      <FlowHandle
        type="target"
        position={Position.Left}
        className="!-left-1.5 !top-1/2 !bg-indigo-400"
      />

      <FlowNodeShell
        selected={selected}
        accentClass="border-indigo-500/20"
        title="CRM Action"
        subtitle={data.label || "External API"}
        widthClass="w-[380px]"
        icon={
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10">
            {integration === "custom_webhook" ? (
              <Webhook className="h-4 w-4 text-indigo-300" />
            ) : (
              <Building2 className="h-4 w-4 text-indigo-300" />
            )}
          </div>
        }
      >
        <div>
          <label htmlFor={`${id}-integration`} className={flowLabelClassName}>
            Integration type
          </label>
          <select
            id={`${id}-integration`}
            aria-label="Integration type"
            value={integration}
            onChange={(event) =>
              patch({ integration_type: event.target.value as CRMIntegrationType })
            }
            className={cn(flowFieldClassName, "nodrag nowheel")}
          >
            {INTEGRATION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-[108px_minmax(0,1fr)] gap-2">
          <div>
            <label htmlFor={`${id}-method`} className={flowLabelClassName}>
              HTTP method
            </label>
            <select
              id={`${id}-method`}
              aria-label="HTTP method"
              value={data.method || "POST"}
              onChange={(event) => patch({ method: event.target.value as CRMHttpMethod })}
              className={cn(flowFieldClassName, "nodrag nowheel")}
            >
              {METHOD_OPTIONS.map((method) => (
                <option key={method} value={method}>
                  {method}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={flowLabelClassName}>Response variable</label>
            <input
              value={data.response_variable || "crm_result"}
              onChange={(event) =>
                patch({ response_variable: event.target.value || "crm_result" })
              }
              placeholder="crm_result"
              className={cn(flowFieldClassName, "nodrag nowheel")}
            />
          </div>
        </div>

        <div>
          <label className={flowLabelClassName}>Endpoint URL</label>
          <input
            value={data.url || ""}
            onChange={(event) => patch({ url: event.target.value })}
            placeholder="https://example.amocrm.ru/api/v4/leads"
            className={cn(flowFieldClassName, "nodrag nowheel")}
          />
          <div className="mt-1.5 flex flex-wrap gap-1">
            {VARIABLE_CHIPS.map((token) => (
              <button
                key={token}
                type="button"
                onClick={() => insertVariable(token)}
                className={cn(
                  "nodrag rounded-full border border-zinc-800 bg-zinc-950/80 px-2 py-0.5",
                  "text-[10px] font-medium text-zinc-500 transition",
                  "hover:border-indigo-500/40 hover:bg-indigo-500/10 hover:text-indigo-200",
                )}
              >
                {token}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label className={flowLabelClassName}>Headers</label>
            <button
              type="button"
              onClick={addHeader}
              className="nodrag inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-indigo-300 hover:bg-indigo-500/10"
            >
              <Plus className="h-3 w-3" />
              Add
            </button>
          </div>
          <div className="space-y-1.5">
            {(data.headers ?? []).map((header) => (
              <div key={header.id} className="flex items-center gap-1.5">
                <input
                  value={header.key}
                  onChange={(event) => updateHeader(header.id, "key", event.target.value)}
                  placeholder="Authorization"
                  className={cn(flowFieldClassName, "min-w-0 flex-1")}
                />
                <input
                  value={header.value}
                  onChange={(event) => updateHeader(header.id, "value", event.target.value)}
                  placeholder="Bearer {{token}}"
                  className={cn(flowFieldClassName, "min-w-0 flex-[1.4]")}
                />
                <button
                  type="button"
                  onClick={() => removeHeader(header.id)}
                  className="nodrag rounded-md p-1.5 text-zinc-600 transition hover:bg-zinc-800 hover:text-red-300"
                  aria-label="Remove header"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor={`${id}-body`} className={flowLabelClassName}>
            <span className="inline-flex items-center gap-1.5">
              <Braces className="h-3 w-3" />
              JSON body template
            </span>
          </label>
          <textarea
            id={`${id}-body`}
            aria-label="JSON body template"
            value={data.body_template || ""}
            onChange={(event) => patch({ body_template: event.target.value })}
            rows={5}
            placeholder={'{\n  "phone": "{{phone}}",\n  "lead_name": "Lead from WhatsApp"\n}'}
            className={cn(flowTextareaClassName, "nodrag nowheel")}
          />
          <p className="mt-1 text-[10px] leading-relaxed text-zinc-600">
            Interpolates session variables. Response JSON is saved to{" "}
            <code className="text-indigo-300/90">
              {`{{${data.response_variable || "crm_result"}}}`}
            </code>
            .
          </p>
        </div>
      </FlowNodeShell>

      <FlowHandle
        type="source"
        position={Position.Right}
        id="default"
        className="!-right-1.5 !top-1/2 !bg-indigo-500"
      />
    </FlowNodeWrapper>
  );
}

/** Canonical registry name used across the builder. */
export { CrmNode as CRMNode, CrmNode as CRMActionNode };
