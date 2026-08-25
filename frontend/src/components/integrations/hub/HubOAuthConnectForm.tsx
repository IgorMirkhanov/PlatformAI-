"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { HubProvider } from "@/types/integration-hub";

interface HubOAuthConnectFormProps {
  provider: HubProvider | string;
  hint?: string;
  submitting: boolean;
  error?: string | null;
  onSubmit: (extra: { subdomain?: string; domain?: string }) => Promise<void>;
  onCancel?: () => void;
}

export function HubOAuthConnectForm({
  provider,
  hint,
  submitting,
  error,
  onSubmit,
  onCancel,
}: HubOAuthConnectFormProps) {
  const needsSubdomain = provider === "amocrm" || provider === "kommo";
  const [value, setValue] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = async (): Promise<void> => {
    setLocalError(null);
    const trimmed = value.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    if (needsSubdomain && !trimmed) {
      setLocalError("Укажите поддомен amoCRM.");
      return;
    }
    if (needsSubdomain) {
      await onSubmit({ subdomain: trimmed.replace(/\.amocrm\.ru$/i, "") });
      return;
    }
    await onSubmit(trimmed ? { domain: trimmed } : {});
  };

  return (
    <form
      className="mt-4 space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
    >
      <label className="block text-xs font-medium text-zinc-400">
        {needsSubdomain ? "Поддомен amoCRM" : "Домен портала (необязательно)"}
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={needsSubdomain ? "acme" : "company.bitrix24.ru"}
          className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
        />
      </label>
      {hint ? <p className="text-[11px] text-zinc-500">{hint}</p> : null}
      {localError || error ? <p className="text-xs text-rose-300">{localError || error}</p> : null}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={submitting} className="bg-violet-600 text-white hover:bg-violet-500">
          {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Открыть окно авторизации
        </Button>
        {onCancel ? (
          <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={onCancel}>
            Отмена
          </Button>
        ) : null}
      </div>
    </form>
  );
}
