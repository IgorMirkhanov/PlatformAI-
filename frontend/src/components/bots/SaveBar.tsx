"use client";

import { Loader2, Save } from "lucide-react";

interface SaveBarProps {
  onSave: () => void | Promise<void>;
  saving: boolean;
  label?: string;
}

export function SaveBar({ onSave, saving, label = "Сохранить изменения" }: SaveBarProps) {
  return (
    <div className="sticky bottom-0 z-20 mt-8">
      <div className="moonai-save-bar flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <p className="text-xs text-zinc-500">
          {saving ? "Синхронизация с сервером…" : "Изменения применяются через PATCH в фоне"}
        </p>
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {saving ? "Сохранение…" : label}
        </button>
      </div>
    </div>
  );
}
