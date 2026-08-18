"use client";

import { CreditCard, ShieldCheck } from "lucide-react";

export function BillingPaymentsPanel() {
  return (
    <section className="rounded-2xl border border-zinc-800/80 bg-zinc-950/60 p-6 backdrop-blur-xl">
      <div className="mb-5 flex items-center gap-2">
        <CreditCard className="h-4 w-4 text-violet-400" />
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Способы оплаты</h3>
          <p className="text-xs text-zinc-500">Банковские карты и корпоративные реквизиты</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-zinc-800/80 bg-black/30 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-zinc-100">Visa •••• 4242</p>
              <p className="mt-1 text-xs text-zinc-500">Основная карта · истекает 09/28</p>
            </div>
            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-300 ring-1 ring-emerald-500/20">
              Default
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 p-4 text-sm text-zinc-400">
          <ShieldCheck className="h-4 w-4 text-violet-400" />
          PCI-ready mock checkout для enterprise workspace
        </div>
      </div>
    </section>
  );
}
