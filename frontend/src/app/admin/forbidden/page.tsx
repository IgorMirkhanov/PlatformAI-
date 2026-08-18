"use client";

import Link from "next/link";
import { ShieldAlert } from "lucide-react";

export default function AdminForbiddenPage() {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-lg flex-col items-center justify-center px-4 py-16 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-red-500/10 ring-1 ring-red-500/30">
        <ShieldAlert className="h-7 w-7 text-red-300" />
      </div>
      <p className="mt-6 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
        403 Forbidden
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-50">
        Нет доступа к админ-панели
      </h1>
      <p className="mt-3 max-w-md text-sm text-zinc-500">
        У этой учётной записи нет роли Admin или Superadmin. Войдите под
        администратором или запросите выдачу прав.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/admin/login"
          className="rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-amber-400"
        >
          Войти в админку
        </Link>
        <Link
          href="/dashboard"
          className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm font-medium text-zinc-300 transition hover:bg-zinc-900"
        >
          В пользовательский кабинет
        </Link>
      </div>
    </div>
  );
}
