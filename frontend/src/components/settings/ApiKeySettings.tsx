"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, Trash2, XCircle } from "lucide-react";

import {
  deleteOrganizationApiKey,
  fetchOrganizationApiKeys,
  upsertOrganizationApiKey,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type { OrganizationApiKeyProviderStatus } from "@/types/organization-api-keys";
import { LLM_API_KEY_PROVIDERS } from "@/types/organization-api-keys";

export function ApiKeySettings() {
  const [items, setItems] = useState<OrganizationApiKeyProviderStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingProvider, setSavingProvider] = useState<string | null>(null);
  const [deletingProvider, setDeletingProvider] = useState<string | null>(null);

  const statusByProvider = useMemo(() => {
    const map = new Map<string, OrganizationApiKeyProviderStatus>();
    for (const item of items) {
      map.set(item.provider, item);
    }
    return map;
  }, [items]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchOrganizationApiKeys();
      setItems(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить API-ключи.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSave = async (provider: string) => {
    const apiKey = (drafts[provider] || "").trim();
    if (!apiKey) {
      setError("Введите API-ключ перед сохранением.");
      return;
    }
    setSavingProvider(provider);
    setError(null);
    try {
      await upsertOrganizationApiKey({ provider, api_key: apiKey, is_active: true });
      setDrafts((prev) => ({ ...prev, [provider]: "" }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить ключ.");
    } finally {
      setSavingProvider(null);
    }
  };

  const handleDelete = async (provider: string) => {
    setDeletingProvider(provider);
    setError(null);
    try {
      await deleteOrganizationApiKey(provider);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить ключ.");
    } finally {
      setDeletingProvider(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-zinc-800 bg-zinc-950/60 p-6 text-sm text-zinc-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загрузка API-ключей…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-950/60 p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/10">
            <KeyRound className="h-5 w-5 text-violet-300" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-zinc-50">LLM API Keys</h2>
            <p className="mt-1 text-sm text-zinc-400">
              Подключите собственные ключи провайдеров. Они шифруются и используются LLM Gateway
              вместо системных ключей платформы.
            </p>
          </div>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4">
        {LLM_API_KEY_PROVIDERS.map((provider) => {
          const status = statusByProvider.get(provider.id);
          const configured = Boolean(status?.configured);
          const saving = savingProvider === provider.id;
          const deleting = deletingProvider === provider.id;

          return (
            <section
              key={provider.id}
              className="rounded-2xl border border-zinc-800 bg-[#0d0d0f]/90 p-5"
            >
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">{provider.label}</h3>
                  <p className="text-xs text-zinc-500">{provider.id}</p>
                </div>
                <div
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
                    configured
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-zinc-700 bg-zinc-900 text-zinc-400",
                  )}
                >
                  {configured ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  {configured ? "Ключ настроен" : "Не настроен"}
                </div>
              </div>

              {configured && status?.masked_key ? (
                <p className="mb-3 font-mono text-xs text-zinc-500">
                  Текущий ключ: {status.masked_key}
                </p>
              ) : null}

              <label className="flex flex-col gap-1.5">
                <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                  API Key
                </span>
                <input
                  type="password"
                  value={drafts[provider.id] ?? ""}
                  onChange={(event) =>
                    setDrafts((prev) => ({ ...prev, [provider.id]: event.target.value }))
                  }
                  placeholder={configured ? "Введите новый ключ для замены" : "sk-..."}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 font-mono text-sm text-zinc-100 outline-none focus:border-violet-500/50"
                />
              </label>

              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={saving || deleting}
                  onClick={() => void handleSave(provider.id)}
                  className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Сохранить
                </button>
                {configured ? (
                  <button
                    type="button"
                    disabled={saving || deleting}
                    onClick={() => void handleDelete(provider.id)}
                    className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 px-4 py-2 text-xs font-semibold text-zinc-300 hover:border-red-500/40 hover:text-red-300 disabled:opacity-50"
                  >
                    {deleting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                    Удалить
                  </button>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
