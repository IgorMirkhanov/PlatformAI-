"use client";

import type { FlowNodeData, ImageAspectRatio, ImageGenerationNodeData, MediaProvider } from "@/types/flow";

type PatchFn = (partial: Partial<FlowNodeData>) => void;

const inputClass =
  "w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-zinc-600";
const textareaClass = `${inputClass} min-h-[120px] resize-y font-mono text-xs`;

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

export function ImageGenerationNodeConfig({
  data,
  patch,
}: {
  data: ImageGenerationNodeData;
  patch: PatchFn;
}) {
  return (
    <>
      <Field label="Provider">
        <select
          className={inputClass}
          value={data.provider}
          onChange={(e) => {
            const provider = e.target.value as MediaProvider;
            patch({
              provider,
              model_name:
                provider === "kling"
                  ? "kling-v1"
                  : "nano-banana-pro",
            });
          }}
        >
          <option value="kling">Kling AI</option>
          <option value="nanobanana">Nano Banana Pro</option>
        </select>
      </Field>

      <Field label="Model">
        <input
          className={inputClass}
          value={data.model_name}
          onChange={(e) => patch({ model_name: e.target.value })}
          placeholder={data.provider === "kling" ? "kling-v1" : "nano-banana-pro"}
        />
      </Field>

      <Field label="Prompt template">
        <textarea
          className={textareaClass}
          value={data.prompt_template}
          onChange={(e) => patch({ prompt_template: e.target.value })}
          placeholder={
            "Studio product photo of {{ session.variables.product_name }}, soft lighting"
          }
        />
      </Field>

      <p className="text-[11px] text-zinc-600">
        Use Jinja2 placeholders such as{" "}
        <code className="text-zinc-400">{`{{ session.variables.product_name }}`}</code>.
      </p>

      <Field label="Aspect ratio">
        <select
          className={inputClass}
          value={data.aspect_ratio}
          onChange={(e) => patch({ aspect_ratio: e.target.value as ImageAspectRatio })}
        >
          <option value="1:1">1:1 (square)</option>
          <option value="16:9">16:9 (landscape)</option>
          <option value="9:16">9:16 (portrait)</option>
        </select>
      </Field>

      <Field label="Result variable">
        <input
          className={inputClass}
          value={data.result_variable}
          onChange={(e) => patch({ result_variable: e.target.value })}
          placeholder="generated_image_url"
        />
      </Field>
    </>
  );
}
