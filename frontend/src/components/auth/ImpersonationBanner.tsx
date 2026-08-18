"use client";

import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";

import { useAuthOptional } from "@/components/auth/AuthContext";
import {
  getImpersonationMeta,
  getOriginalAdminSnapshot,
  type ImpersonationMeta,
} from "@/lib/impersonation";

export function ImpersonationBanner() {
  const auth = useAuthOptional();
  const [meta, setMeta] = useState<ImpersonationMeta | null>(null);
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const snapshot = getOriginalAdminSnapshot();
    const nextMeta = auth?.impersonationMeta ?? getImpersonationMeta();
    setVisible(Boolean(snapshot));
    setMeta(nextMeta);
  }, [auth?.impersonationMeta, auth?.isImpersonating]);

  if (!visible || !meta) {
    return null;
  }

  const handleExit = async () => {
    if (exiting) return;
    setExiting(true);
    try {
      if (auth?.exitImpersonation) {
        await auth.exitImpersonation();
      } else {
        window.location.assign("/admin");
      }
    } finally {
      setExiting(false);
    }
  };

  return (
    <div
      role="status"
      className="sticky top-0 z-[60] flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-amber-600/60 bg-gradient-to-r from-amber-700 to-red-800 px-4 py-2.5 text-sm text-white shadow-lg shadow-red-950/40"
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-white" />
        <p className="min-w-0 leading-snug">
          ⚠️ Вы находитесь в режиме поддержки под аккаунтом:{" "}
          <span className="font-semibold text-white">{meta.email}</span>
          {meta.company_name ? (
            <span className="text-red-100/90"> · {meta.company_name}</span>
          ) : null}
          . Вся активность записывается в Audit Log.
        </p>
      </div>
      <button
        type="button"
        onClick={() => void handleExit()}
        disabled={exiting}
        className="inline-flex shrink-0 items-center justify-center rounded-lg border border-white/40 bg-black/30 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-white transition hover:border-white/70 hover:bg-black/50 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {exiting ? "Выход…" : "Вернуться в админку"}
      </button>
    </div>
  );
}
