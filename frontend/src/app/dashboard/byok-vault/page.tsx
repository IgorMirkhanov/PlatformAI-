"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  createVaultCredential,
  fetchVaultCredentials,
  revalidateVaultCredential,
  type VaultCredential,
} from "@/lib/api";
import { canManageSettings } from "@/lib/permissions";
import { useBotStore } from "@/store/useBotStore";

const KINDS = [
  "llm_openai",
  "llm_deepseek",
  "channel_telegram",
  "channel_wazzup",
  "crm_amocrm",
  "crm_bitrix24",
];

export default function ByokVaultPage() {
  const currentUser = useBotStore((s) => s.currentUser);
  const loadCurrentUser = useBotStore((s) => s.loadCurrentUser);
  const allowed = canManageSettings(currentUser?.role);
  const [items, setItems] = useState<VaultCredential[]>([]);
  const [kind, setKind] = useState("llm_openai");
  const [secret, setSecret] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function reload() {
    const data = await fetchVaultCredentials();
    setItems(data.items);
  }

  useEffect(() => {
    if (!currentUser) void loadCurrentUser();
  }, [currentUser, loadCurrentUser]);

  useEffect(() => {
    if (!allowed) return;
    void reload().catch((exc) => {
      setError(exc instanceof Error ? exc.message : "Не удалось загрузить vault.");
    });
  }, [allowed]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createVaultCredential({
        kind,
        label: label || undefined,
        validate_before_save: true,
        payload: { api_key: secret, token: secret, bot_token: secret },
      });
      setSecret("");
      await reload();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ключ не сохранён.");
    } finally {
      setSaving(false);
    }
  }

  if (!currentUser) {
    return (
      <div data-testid="byok-loading" className="px-4 py-10 text-sm text-zinc-400">
        Загрузка…
      </div>
    );
  }

  if (!allowed) {
    return <div className="px-4 py-10 text-sm text-zinc-400">Недостаточно прав для BYOK vault.</div>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-xl font-semibold text-white">BYOK Vault</h1>
        <p className="mt-1 text-sm text-zinc-500">Ключ проверяется ping-запросом до сохранения.</p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
        <label className="block text-xs text-zinc-400">
          Тип
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-white"
          >
            {KINDS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-zinc-400">
          Метка
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-white"
          />
        </label>
        <label className="block text-xs text-zinc-400">
          Секрет
          <input
            data-testid="byok-secret"
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-white"
            required
          />
        </label>
        {error ? (
          <p data-testid="byok-error" className="text-sm text-rose-400">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Сохранить
        </button>
      </form>

      <ul className="divide-y divide-zinc-800 rounded-xl border border-zinc-800">
        {items.map((item) => (
          <li data-testid="byok-item" key={item.id} className="flex items-center justify-between px-4 py-3 text-sm">
            <div>
              <p className="text-zinc-100">
                {item.kind} {item.label ? `· ${item.label}` : ""}
              </p>
              <p className="text-xs text-zinc-500">
                {item.status}
                {item.last_error ? ` — ${item.last_error}` : ""}
              </p>
            </div>
            <button
              type="button"
              className="rounded-lg border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
              onClick={() => {
                void revalidateVaultCredential(item.id).then(reload).catch((exc) => {
                  setError(exc instanceof Error ? exc.message : "Проверка не удалась.");
                });
              }}
            >
              Проверить снова
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
