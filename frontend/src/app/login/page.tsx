"use client";

import { FormEvent, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Lock, Mail } from "lucide-react";
import { Suspense } from "react";

import { loginWithPassword } from "@/lib/auth/session";
import { useBotStore } from "@/store/useBotStore";
import { SiteFooter } from "@/components/legal/SiteFooter";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);

  const expired = searchParams.get("expired") === "true";
  const from = searchParams.get("from");

  const redirectTarget = useMemo(() => {
    if (from && from.startsWith("/") && !from.startsWith("//") && !from.startsWith("/login")) {
      return from;
    }
    return "/dashboard";
  }, [from]);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await loginWithPassword(email.trim(), password);
      await loadCurrentUser();
      router.replace(redirectTarget);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-6 shadow-xl">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">MP.AI</p>
        <h1 className="mt-2 text-2xl font-semibold text-zinc-50">Sign in</h1>
        <p className="mt-1 text-sm text-zinc-500">Access your workspace and bot builder.</p>

        {expired ? (
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-950/40 px-3 py-2 text-xs text-amber-100">
            Your session expired. Please sign in again.
          </div>
        ) : null}

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">Email</span>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-950 py-2.5 pl-10 pr-3 text-sm text-zinc-100 outline-none focus:border-zinc-600"
                placeholder="you@company.com"
              />
            </div>
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">Password</span>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-950 py-2.5 pl-10 pr-3 text-sm text-zinc-100 outline-none focus:border-zinc-600"
                placeholder="••••••••"
              />
            </div>
          </label>

          {error ? (
            <p className="rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-200">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="mt-5 flex items-center justify-between text-xs text-zinc-500">
          <Link href="/forgot-password" className="hover:text-zinc-300">
            Forgot password?
          </Link>
          <Link href="/register" className="hover:text-zinc-300">
            Create account
          </Link>
        </div>
      </div>
      <SiteFooter className="mt-8" />
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading…
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
