"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Lock, Mail, Shield } from "lucide-react";

import { canAccessAdminPanel } from "@/lib/auth/admin";
import { loginWithPassword } from "@/lib/auth/session";
import { useBotStore } from "@/store/useBotStore";

function AdminLoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const currentUser = useBotStore((state) => state.currentUser);

  const redirectTarget = useMemo(() => {
    const from = searchParams.get("from");
    if (from && from.startsWith("/admin") && !from.startsWith("//")) {
      return from;
    }
    return "/admin";
  }, [searchParams]);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const currentUserLoading = useBotStore((state) => state.currentUserLoading);

  useEffect(() => {
    void loadCurrentUser();
  }, [loadCurrentUser]);

  useEffect(() => {
    if (currentUserLoading) return;
    if (currentUser && canAccessAdminPanel()) {
      router.replace(redirectTarget);
    }
  }, [currentUser, currentUserLoading, redirectTarget, router]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await loginWithPassword(email.trim(), password);
      await loadCurrentUser();
      const user = useBotStore.getState().currentUser;
      if (!user || !canAccessAdminPanel()) {
        setError("У этой учётной записи нет доступа к админ-панели.");
        return;
      }
      router.replace(redirectTarget);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-6 shadow-xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10 ring-1 ring-amber-500/30">
            <Shield className="h-5 w-5 text-amber-300" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">MP.AI</p>
            <h1 className="text-xl font-semibold text-zinc-50">Вход в админку</h1>
          </div>
        </div>
        <p className="mt-3 text-sm text-zinc-500">
          Только Superadmin и Admin. Обычные пользователи увидят страницу 403, а не кабинет.
        </p>

        {error ? (
          <div className="mt-4 rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-100">
            {error}
          </div>
        ) : null}

        <form onSubmit={(e) => void onSubmit(e)} className="mt-6 space-y-4">
          <label className="block text-xs font-medium text-zinc-400">
            Email
            <div className="relative mt-1.5">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-950 py-2.5 pl-10 pr-3 text-sm text-zinc-100 outline-none ring-amber-500/30 focus:ring-2"
              />
            </div>
          </label>
          <label className="block text-xs font-medium text-zinc-400">
            Пароль
            <div className="relative mt-1.5">
              <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-950 py-2.5 pl-10 pr-3 text-sm text-zinc-100 outline-none ring-amber-500/30 focus:ring-2"
              />
            </div>
          </label>
          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-amber-500 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-amber-400 disabled:opacity-60"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Войти
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-zinc-600">
          <Link href="/dashboard" className="text-zinc-400 hover:text-zinc-200">
            ← Вернуться в кабинет
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-black" />}>
      <AdminLoginForm />
    </Suspense>
  );
}
