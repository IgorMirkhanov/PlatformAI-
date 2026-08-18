"use client";

import { FormEvent, useState } from "react";
import { Loader2, ShieldAlert } from "lucide-react";

import { useAuth } from "@/components/auth/AuthContext";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function AdminImpersonatePage() {
  const { startImpersonation } = useAuth();
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const cleaned = email.trim().toLowerCase();
    if (!cleaned.includes("@")) {
      showToast("Enter a valid client email.", "error");
      return;
    }
    if (!password.trim()) {
      showToast("Re-enter your admin password to continue.", "error");
      return;
    }
    setPending(true);
    try {
      await startImpersonation(cleaned, password);
      showToast(`Logged in as ${cleaned}`, "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Impersonation failed."), "error");
      setPending(false);
    }
  };

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">Impersonate</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Enter a client account by email. SUPERADMIN/SUPPORT targets are blocked. Session TTL is
          1 hour; ending the session revokes the JWT immediately. Every start/end is audited.
        </p>
      </header>

      <div className="rounded-2xl border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-100">
        <div className="flex gap-2">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Critical actions (billing writes, Stripe checkout, admin balance adjust) are blocked
            while impersonating. Exit support mode before privileged mutations. Password re-auth is
            required on every start.
          </p>
        </div>
      </div>

      <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="block space-y-2">
          <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            Client email
          </span>
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="client@company.com"
            autoComplete="off"
            className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 outline-none ring-amber-500/30 placeholder:text-zinc-600 focus:ring-2"
          />
        </label>
        <label className="block space-y-2">
          <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            Your admin password
          </span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Confirm identity"
            autoComplete="current-password"
            className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 outline-none ring-amber-500/30 placeholder:text-zinc-600 focus:ring-2"
          />
        </label>
        <button
          type="submit"
          disabled={pending}
          className="inline-flex w-full items-center justify-center rounded-xl bg-amber-400 px-4 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-amber-300 disabled:opacity-60"
        >
          {pending ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Starting session…
            </>
          ) : (
            "Login as user"
          )}
        </button>
      </form>
    </div>
  );
}
