"use client";

import { useMemo, useState } from "react";
import { Check, Copy, Loader2 } from "lucide-react";

import { Toggle } from "@/components/ui/Toggle";
import { buildWidgetEmbedScript } from "@/types/channels";
import type { ChannelStatus, SetupChannelRequest } from "@/types/channels";

interface WebWidgetChannelFormProps {
  botId: string;
  status: ChannelStatus;
  saving: boolean;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function WebWidgetChannelForm({
  botId,
  status,
  saving,
  onSubmit,
}: WebWidgetChannelFormProps) {
  const [active, setActive] = useState<boolean>(status.active ?? true);
  const [copied, setCopied] = useState(false);

  const embedScript = useMemo(
    () => status.embed_script ?? buildWidgetEmbedScript(botId),
    [botId, status.embed_script],
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    await onSubmit({
      channel_type: "web_widget",
      web_widget_active: active,
    });
  };

  const handleCopy = async (): Promise<void> => {
    await navigator.clipboard.writeText(embedScript);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
        <p className="text-sm font-medium text-zinc-100">Embeddable Web Widget</p>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
          Скопируйте snippet и вставьте перед закрывающим тегом{" "}
          <code className="text-violet-300">&lt;/body&gt;</code> на любом внешнем сайте.
        </p>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <label htmlFor="widget-snippet" className="text-xs text-zinc-500">
            Integration script
          </label>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="inline-flex items-center gap-1 text-[11px] text-violet-300 hover:text-violet-200"
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Скопировано" : "Скопировать код"}
          </button>
        </div>
        <textarea
          id="widget-snippet"
          readOnly
          rows={4}
          value={embedScript}
          className="w-full resize-none rounded-xl border border-zinc-800 bg-black/50 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-zinc-300 focus:outline-none focus:border-violet-500"
        />
      </div>

      <div className="flex items-center justify-between rounded-xl border border-zinc-800/80 bg-zinc-950/40 px-4 py-3">
        <div>
          <p className="text-sm font-medium text-zinc-200">Виджет активен</p>
          <p className="text-xs text-zinc-500">Принимать сообщения с внешних сайтов</p>
        </div>
        <Toggle checked={active} onChange={setActive} />
      </div>

      <button
        type="submit"
        disabled={saving}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-500 disabled:opacity-60 shadow-glow-purple"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        {status.connected ? "Обновить виджет" : "Активировать виджет"}
      </button>
    </form>
  );
}
