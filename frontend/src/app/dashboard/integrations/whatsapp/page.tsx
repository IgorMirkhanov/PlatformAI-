"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Loader2,
  MessageSquare,
  Phone,
  QrCode,
  RefreshCw,
  Send,
  Unplug,
  User,
  X,
} from "lucide-react";

import { WhatsAppQrModal } from "@/components/channel-hub/WhatsAppQrModal";
import { useAsyncAction } from "@/lib/hooks/use-async-action";
import {
  fetchWhatsAppSession,
  sendWhatsAppTestMessage,
  stopWhatsAppSession,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useBotStore } from "@/store/useBotStore";
import type { WhatsAppSessionStatus } from "@/types/channel-hub";

type UiStatus = "connected" | "waiting" | "disconnected";

function mapStatus(raw: string | undefined, hubConnected: boolean): UiStatus {
  if (hubConnected || raw === "connected") return "connected";
  if (raw === "pending") return "waiting";
  return "disconnected";
}

function StatusBadge({ status }: { status: UiStatus }) {
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-semibold text-emerald-300 ring-1 ring-emerald-500/30">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
        </span>
        Connected
      </span>
    );
  }
  if (status === "waiting") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-amber-500/15 px-3 py-1 text-xs font-semibold text-amber-200 ring-1 ring-amber-500/30">
        <span className="h-2 w-2 rounded-full bg-amber-400" />
        Waiting for Scan
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-red-500/15 px-3 py-1 text-xs font-semibold text-red-300 ring-1 ring-red-500/30">
      <span className="h-2 w-2 rounded-full bg-red-400" />
      Disconnected
    </span>
  );
}

function WhatsAppIntegrationsPageInner() {
  const searchParams = useSearchParams();
  const { showToast } = useToast();
  const activeBotId = useBotStore((s) => s.activeBotId);
  const agentProfiles = useBotStore((s) => s.agentProfiles);
  const connection = useBotStore((s) => s.connection);

  const botId = useMemo(() => {
    return (
      searchParams.get("botId") ||
      activeBotId ||
      connection?.botId ||
      Object.keys(agentProfiles)[0] ||
      null
    );
  }, [activeBotId, agentProfiles, connection?.botId, searchParams]);

  const [session, setSession] = useState<WhatsAppSessionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [qrOpen, setQrOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [testText, setTestText] = useState("Hello from MP.AI WhatsApp test ✅");

  const loadSession = useCallback(async () => {
    if (!botId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await fetchWhatsAppSession(botId);
      setSession(data);
    } catch {
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const uiStatus = mapStatus(session?.status, Boolean(session?.hub_connected));

  const disconnectAction = useAsyncAction(
    async () => {
      if (!botId) throw new Error("Select a bot first.");
      await stopWhatsAppSession(botId);
      setSession((prev) =>
        prev
          ? {
              ...prev,
              status: "disconnected",
              phone: null,
              push_name: null,
              connected_at: null,
              has_qr: false,
              hub_connected: false,
              hub_reference_id: null,
            }
          : prev,
      );
      setConfirmOpen(false);
    },
    {
      successMessage: "WhatsApp session disconnected.",
      errorMessage: "Failed to disconnect WhatsApp session.",
    },
  );

  const testAction = useAsyncAction(
    async () => {
      if (!botId) throw new Error("Select a bot first.");
      if (!testTo.trim()) throw new Error("Enter a phone number.");
      await sendWhatsAppTestMessage(botId, {
        to: testTo.trim(),
        text: testText.trim() || "Test message",
      });
      setTestOpen(false);
    },
    {
      successMessage: "Test message sent.",
      errorMessage: "Failed to send test message.",
    },
  );

  if (!botId) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-6 text-center">
          <h1 className="text-xl font-semibold text-zinc-50">WhatsApp Integration</h1>
          <p className="mt-2 text-sm text-zinc-500">
            Select an agent first, then open this page with{" "}
            <code className="text-zinc-300">?botId=…</code>
          </p>
          <Link href="/dashboard" className="mt-4 inline-block text-sm text-violet-400">
            Go to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8 lg:px-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#25D366]/80">
            Integrations
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-zinc-50">WhatsApp</h1>
          <p className="mt-2 text-sm text-zinc-500">
            Baileys QR session · bot{" "}
            <span className="font-mono text-zinc-400">{botId.slice(0, 8)}…</span>
          </p>
        </div>
        <StatusBadge status={uiStatus} />
      </header>

      <section className="rounded-2xl border border-zinc-800/80 bg-[#0d0d0f]/90 p-5">
        {loading ? (
          <div className="flex min-h-[120px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[#25D366]" />
          </div>
        ) : uiStatus === "connected" ? (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-zinc-100">Connected account</h2>
            <dl className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                <dt className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-zinc-500">
                  <Phone className="h-3.5 w-3.5" /> Phone
                </dt>
                <dd className="mt-1 text-sm font-medium text-zinc-100">
                  {session?.phone || session?.hub_reference_id || "—"}
                </dd>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                <dt className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-zinc-500">
                  <User className="h-3.5 w-3.5" /> Push name
                </dt>
                <dd className="mt-1 text-sm font-medium text-zinc-100">
                  {session?.push_name || "—"}
                </dd>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                <dt className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-zinc-500">
                  Connected since
                </dt>
                <dd className="mt-1 text-sm font-medium text-zinc-100">
                  {session?.connected_at
                    ? new Date(session.connected_at).toLocaleString()
                    : "—"}
                </dd>
              </div>
            </dl>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setTestOpen(true)}
                className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900"
              >
                <MessageSquare className="h-4 w-4" />
                Test Message
              </button>
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                className="inline-flex items-center gap-2 rounded-xl border border-red-500/40 px-3 py-2 text-sm text-red-300 hover:bg-red-500/10"
              >
                <Unplug className="h-4 w-4" />
                Disconnect Session
              </button>
              <button
                type="button"
                onClick={() => void loadSession()}
                className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 px-3 py-2 text-sm text-zinc-400 hover:bg-zinc-900"
              >
                <RefreshCw className="h-4 w-4" />
                Refresh status
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#25D366]/15 ring-1 ring-[#25D366]/30">
                <QrCode className="h-5 w-5 text-[#25D366]" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-zinc-100">Connect via QR</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Scan with WhatsApp → Linked devices. Session credentials persist on the server.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setQrOpen(true)}
              className="inline-flex items-center gap-2 rounded-xl bg-[#25D366] px-4 py-2.5 text-sm font-semibold text-black hover:bg-[#2fe074]"
            >
              <QrCode className="h-4 w-4" />
              {uiStatus === "waiting" ? "Show QR again" : "Connect WhatsApp"}
            </button>
          </div>
        )}
      </section>

      <p className="text-xs text-zinc-600">
        Prefer Cloud API / WABA?{" "}
        <Link
          href={`/dashboard/channels-agent/${botId}/waba`}
          className="text-violet-400 hover:text-violet-300"
        >
          Open WABA setup
        </Link>
      </p>

      <WhatsAppQrModal
        open={qrOpen}
        botId={botId}
        onClose={() => setQrOpen(false)}
        onConnected={(meta) => {
          showToast("WhatsApp connected.", "success");
          setQrOpen(false);
          setSession((prev) => ({
            bot_id: botId,
            status: "connected",
            phone: meta?.phone || prev?.phone || null,
            push_name: meta?.pushName || prev?.push_name || null,
            connected_at: new Date().toISOString(),
            has_qr: false,
            hub_connected: true,
            hub_reference_id: meta?.phone || prev?.hub_reference_id || null,
          }));
          void loadSession();
        }}
      />

      {confirmOpen ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5">
            <h2 className="text-lg font-semibold text-zinc-50">Disconnect session?</h2>
            <p className="mt-2 text-sm text-zinc-500">
              This wipes Baileys auth files and marks the channel disconnected. You will need to
              scan a new QR to reconnect.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={disconnectAction.isLoading}
                className="rounded-xl border border-zinc-800 px-4 py-2 text-sm text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void disconnectAction.run()}
                disabled={disconnectAction.isLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {disconnectAction.isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Unplug className="h-4 w-4" />
                )}
                Disconnect
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {testOpen ? (
        <div
          className="fixed inset-0 z-[80] flex items-end justify-center bg-black/70 px-4 py-6 backdrop-blur-sm sm:items-center"
          onClick={() => !testAction.isLoading && setTestOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-zinc-50">Test Message</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Send a text via the live Baileys session to verify connectivity.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setTestOpen(false)}
                className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <label className="block space-y-1.5">
                <span className="text-xs text-zinc-400">Phone (digits, country code)</span>
                <input
                  value={testTo}
                  onChange={(e) => setTestTo(e.target.value)}
                  placeholder="77001234567"
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm outline-none focus:border-zinc-600"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs text-zinc-400">Message</span>
                <textarea
                  value={testText}
                  onChange={(e) => setTestText(e.target.value)}
                  rows={3}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm outline-none focus:border-zinc-600"
                />
              </label>
            </div>
            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={() => void testAction.run()}
                disabled={testAction.isLoading}
                className={cn(
                  "inline-flex items-center gap-2 rounded-xl bg-[#25D366] px-4 py-2 text-sm font-semibold text-black",
                  "disabled:opacity-50",
                )}
              >
                {testAction.isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                Send test
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function WhatsAppIntegrationsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center text-sm text-zinc-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading…
        </div>
      }
    >
      <WhatsAppIntegrationsPageInner />
    </Suspense>
  );
}
