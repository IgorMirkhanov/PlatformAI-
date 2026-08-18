"use client";

import Link from "next/link";
import { Settings, Users } from "lucide-react";

export default function SettingsPage() {
  const apiLabel =
    typeof window !== "undefined"
      ? `${window.location.origin}/api/v1`
      : "Same origin (/api/v1)";

  const wsLabel =
    typeof window !== "undefined"
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`
      : "Same origin (/ws)";

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6 lg:p-8">
      <div className="glass-panel rounded-xl p-8">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-700/30">
          <Settings className="h-6 w-6 text-zinc-300" />
        </div>
        <h1 className="text-2xl font-semibold text-zinc-100">Настройки workspace</h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-zinc-400">
          Управление командой, API-доступом и параметрами окружения MP.AI.
        </p>
      </div>

      <Link
        href="/settings/team"
        className="moonai-panel flex items-center gap-4 transition hover:border-violet-500/30 hover:bg-violet-500/5"
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/20">
          <Users className="h-5 w-5 text-violet-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-zinc-100">Управление командой</p>
          <p className="text-xs text-zinc-500">Роли, приглашения и доступ к разделам платформы</p>
        </div>
      </Link>

      <div className="glass-panel space-y-4">
        {[
          { label: "API Base URL", value: apiLabel },
          { label: "WebSocket Gateway", value: wsLabel },
          { label: "Environment", value: "Development" },
        ].map((item) => (
          <div
            key={item.label}
            className="flex items-center justify-between rounded-lg border border-zinc-800 bg-black/30 px-4 py-3"
          >
            <span className="text-sm text-zinc-400">{item.label}</span>
            <span className="text-sm font-medium text-zinc-200">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
