"use client";

import { Copy, Loader2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { useToast } from "@/hooks/useToast";
import {
  createWebhookSubscription,
  deleteWebhookSubscription,
  listWebhookSubscriptions,
  updateWebhookSubscription,
  type CrmWebhookSubscription,
} from "@/lib/crm/api";
import type { CrmWebhookEventType } from "@/lib/crm/types";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";

const EVENT_OPTIONS: CrmWebhookEventType[] = [
  "deal.created",
  "deal.updated",
  "deal.closed",
  "contact.created",
  "*",
];

function generateSecret(): string {
  const bytes = new Uint8Array(24);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function maskSecret(secret: string): string {
  if (secret.length <= 8) return "••••••••";
  return `${secret.slice(0, 4)}…${secret.slice(-4)}`;
}

export default function CrmWebhooksPage() {
  const { showToast } = useToast();
  const [items, setItems] = useState<CrmWebhookSubscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [targetUrl, setTargetUrl] = useState("");
  const [secret, setSecret] = useState(() => generateSecret());
  const [events, setEvents] = useState<CrmWebhookEventType[]>(["deal.created", "deal.closed"]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listWebhookSubscriptions();
      setItems(response.items);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить вебхуки."), "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const toggleEvent = (event: CrmWebhookEventType) => {
    setEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event],
    );
  };

  const onCreate = async (formEvent: FormEvent) => {
    formEvent.preventDefault();
    if (!targetUrl.trim() || events.length === 0 || saving) return;
    setSaving(true);
    try {
      await createWebhookSubscription({
        target_url: targetUrl.trim(),
        event_types: events,
        secret: secret.trim() || undefined,
        is_active: true,
      });
      setTargetUrl("");
      setSecret(generateSecret());
      setEvents(["deal.created", "deal.closed"]);
      setShowForm(false);
      showToast("Вебхук создан.", "success");
      await reload();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать вебхук."), "error");
    } finally {
      setSaving(false);
    }
  };

  const onToggleActive = async (row: CrmWebhookSubscription) => {
    try {
      await updateWebhookSubscription(row.id, { is_active: !row.is_active });
      await reload();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить статус."), "error");
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteWebhookSubscription(id);
      showToast("Подписка удалена.", "success");
      await reload();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить вебхук."), "error");
    }
  };

  const copySecret = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      showToast("Секрет скопирован.", "success");
    } catch {
      showToast("Не удалось скопировать секрет.", "error");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 md:p-6">
      <header className="space-y-3">
        <CrmSubNav />
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-50">Вебхуки</h1>
            <p className="mt-1 text-sm text-zinc-400">
              Подписки на события CRM: deal.created, deal.closed и др.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setSecret(generateSecret());
              setShowForm((v) => !v);
            }}
            className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-500"
          >
            <Plus className="h-4 w-4" />
            Добавить вебхук
          </button>
        </div>
      </header>

      {showForm ? (
        <form
          onSubmit={(e) => void onCreate(e)}
          className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-950/60 p-4"
        >
          <label className="block text-sm text-zinc-300">
            Target URL (https)
            <input
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              required
              placeholder="https://example.com/hooks/crm"
              className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/50"
            />
          </label>
          <div>
            <p className="text-sm text-zinc-300">События</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {EVENT_OPTIONS.map((event) => {
                const active = events.includes(event);
                return (
                  <button
                    key={event}
                    type="button"
                    onClick={() => toggleEvent(event)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium",
                      active
                        ? "border-violet-500/60 bg-violet-500/15 text-violet-100"
                        : "border-zinc-700 text-zinc-400",
                    )}
                  >
                    {event}
                  </button>
                );
              })}
            </div>
          </div>
          <label className="block text-sm text-zinc-300">
            Секретный токен (HMAC)
            <div className="mt-1.5 flex gap-2">
              <input
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-xs text-zinc-100 outline-none focus:border-violet-500/50"
              />
              <button
                type="button"
                onClick={() => setSecret(generateSecret())}
                className="shrink-0 rounded-xl border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-900"
              >
                Сгенерировать
              </button>
            </div>
          </label>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-300"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={saving || events.length === 0}
              className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Создать
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка…
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-zinc-800">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-zinc-800 bg-zinc-950/80 text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">URL</th>
                <th className="px-4 py-3 font-medium">События</th>
                <th className="px-4 py-3 font-medium">Секрет</th>
                <th className="px-4 py-3 font-medium">Статус</th>
                <th className="px-4 py-3 font-medium">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-zinc-500">
                    Подписок пока нет
                  </td>
                </tr>
              ) : (
                items.map((row) => (
                  <tr key={row.id} className="bg-zinc-950/40">
                    <td className="max-w-[240px] truncate px-4 py-3 font-mono text-xs text-zinc-200">
                      {row.target_url}
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-300">
                      {row.event_types.join(", ")}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => void copySecret(row.secret)}
                        className="inline-flex items-center gap-1.5 font-mono text-xs text-zinc-400 hover:text-zinc-200"
                        title="Скопировать секрет"
                      >
                        {maskSecret(row.secret)}
                        <Copy className="h-3 w-3" />
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => void onToggleActive(row)}
                        className={cn(
                          "rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase",
                          row.is_active
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-zinc-800 text-zinc-500",
                        )}
                      >
                        {row.is_active ? "active" : "off"}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => void onDelete(row.id)}
                        className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Удалить
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
