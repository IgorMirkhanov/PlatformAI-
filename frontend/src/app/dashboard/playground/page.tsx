"use client";

import { FormEvent, useEffect, useState } from "react";

import { sendPlaygroundChat, type PlaygroundChatResponse } from "@/lib/api";
import { canAccessSandbox } from "@/lib/permissions";
import { useBotStore } from "@/store/useBotStore";

export default function PlaygroundPage() {
  const currentUser = useBotStore((s) => s.currentUser);
  const loadCurrentUser = useBotStore((s) => s.loadCurrentUser);
  const activeBotId = useBotStore((s) => s.activeBotId);
  const allowed = canAccessSandbox(currentUser?.role);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<PlaygroundChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!currentUser) void loadCurrentUser();
  }, [currentUser, loadCurrentUser]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!activeBotId) {
      setError("Выберите бота в шапке.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const response = await sendPlaygroundChat({ bot_id: activeBotId, message, dry_run: true });
      setResult(response);
      if (response.wallet_blocked) {
        setError(response.text || "Кошелёк заблокирован. Пополните баланс.");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Playground не ответил.");
    } finally {
      setPending(false);
    }
  }

  if (!currentUser) {
    return (
      <div data-testid="playground-loading" className="px-4 py-10 text-sm text-zinc-400">
        Загрузка…
      </div>
    );
  }

  if (!allowed) {
    return <div className="px-4 py-10 text-sm text-zinc-400">Недостаточно прав для playground.</div>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Playground</h1>
        <p className="mt-1 text-sm text-zinc-500">Dry-run: токены считаются, боевой кошелёк не списывается.</p>
      </div>
      <form onSubmit={onSubmit} className="space-y-3">
        <textarea
          data-testid="playground-input"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          className="min-h-[120px] w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-white"
          placeholder="Сообщение для теста…"
          required
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Отправить
        </button>
      </form>
      {error ? (
        <p data-testid="playground-error" className="text-sm text-rose-400">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className="space-y-3 rounded-xl border border-zinc-800 p-4 text-sm">
          <p className="whitespace-pre-wrap text-zinc-100">{result.text}</p>
          <p className="text-xs text-zinc-500">
            tokens={result.total_tokens} model={result.model_name ?? "—"} dry_run={String(result.dry_run)}
          </p>
          {result.rag_context.length > 0 ? (
            <ul className="space-y-1 text-xs text-zinc-400">
              {result.rag_context.map((chunk, index) => (
                <li key={index}>
                  {chunk.file_name ?? "chunk"} · {chunk.similarity_score.toFixed(2)} — {chunk.text.slice(0, 160)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
