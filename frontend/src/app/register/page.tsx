"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { registerAccount } from "@/lib/auth/session";
import { useBotStore } from "@/store/useBotStore";
import { SiteFooter } from "@/components/legal/SiteFooter";

export default function RegisterPage() {
  const router = useRouter();
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const [fullName, setFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [acceptPd, setAcceptPd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!acceptTerms || !acceptPd) {
      setError("Нужно принять условия и согласие на обработку персональных данных.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await registerAccount({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        company_name: companyName.trim() || "My Organization",
      });
      await loadCurrentUser();
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-6">
        <h1 className="text-2xl font-semibold text-zinc-50">Create account</h1>
        <p className="mt-1 text-sm text-zinc-500">Start your MP.AI workspace.</p>
        <form onSubmit={onSubmit} className="mt-6 space-y-3">
          <input
            className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm"
            placeholder="Full name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            autoComplete="name"
          />
          <input
            className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm"
            placeholder="Company"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            autoComplete="organization"
          />
          <input
            type="email"
            required
            className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
          <input
            type="password"
            required
            minLength={8}
            className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm"
            placeholder="Password (min 8)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
          <label className="flex cursor-pointer items-start gap-2 text-[11px] leading-4 text-zinc-400">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={acceptTerms}
              onChange={(e) => setAcceptTerms(e.target.checked)}
              required
            />
            <span>
              Принимаю{" "}
              <Link href="/terms" className="text-zinc-200 underline">
                условия использования
              </Link>
              ,{" "}
              <Link href="/privacy" className="text-zinc-200 underline">
                политику конфиденциальности
              </Link>{" "}
              и{" "}
              <Link href="/legal/cookies" className="text-zinc-200 underline">
                политику cookie
              </Link>
              .
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2 text-[11px] leading-4 text-zinc-400">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={acceptPd}
              onChange={(e) => setAcceptPd(e.target.checked)}
              required
            />
            <span>
              Даю{" "}
              <Link href="/legal/personal-data" className="text-zinc-200 underline">
                согласие на обработку персональных данных
              </Link>
              .
            </span>
          </label>
          {error ? <p className="text-xs text-red-300">{error}</p> : null}
          <button
            type="submit"
            disabled={loading || !acceptTerms || !acceptPd}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent py-2.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Register
          </button>
        </form>
        <p className="mt-4 text-xs text-zinc-500">
          Already have an account?{" "}
          <Link href="/login" className="text-zinc-300 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
      <SiteFooter className="mt-8" />
    </div>
  );
}
