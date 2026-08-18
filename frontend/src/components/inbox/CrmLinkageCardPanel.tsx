"use client";

import { ExternalLink, Link2, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CrmLinkageCard, CrmPlatformLinkage } from "@/types/inbox";

interface CrmLinkageCardProps {
  crm: CrmLinkageCard;
  creating?: boolean;
  onCreateDeal?: () => void;
}

function PlatformCard({
  title,
  linkage,
  accentClass,
}: {
  title: string;
  linkage: CrmPlatformLinkage | null;
  accentClass: string;
}) {
  if (!linkage?.connected) {
    return null;
  }

  const entityId = linkage.lead_id ?? linkage.deal_id;
  const stage = linkage.stage_label ?? linkage.pipeline_label;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className={cn("text-xs font-semibold uppercase tracking-wider", accentClass)}>
          {title}
        </p>
        <Link2 className="h-3.5 w-3.5 text-zinc-500" />
      </div>

      {entityId ? (
        <div className="mt-3 space-y-1">
          <p className="text-sm font-medium text-zinc-100">
            {linkage.lead_id ? `Lead #${linkage.lead_id}` : `Deal #${linkage.deal_id}`}
          </p>
          {stage ? <p className="text-xs text-zinc-500">{stage}</p> : null}
          <button
            type="button"
            className="mt-2 inline-flex items-center gap-1 text-xs text-violet-300 hover:text-violet-200"
          >
            Открыть в CRM
            <ExternalLink className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <p className="mt-3 text-xs text-zinc-500">Сделка ещё не связана с этим диалогом</p>
      )}

      {!linkage.sync_enabled ? (
        <p className="mt-2 text-[10px] text-amber-400">Синхронизация отключена в настройках бота</p>
      ) : null}
    </div>
  );
}

export function CrmLinkageCardPanel({
  crm,
  creating = false,
  onCreateDeal,
}: CrmLinkageCardProps) {
  const hasConnectedPlatform = Boolean(
    crm.amocrm?.connected || crm.bitrix24?.connected,
  );
  const hasLinkedDeal = Boolean(
    crm.amocrm?.lead_id || crm.bitrix24?.deal_id,
  );

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-zinc-100">amoCRM / Bitrix24</p>
          <p className="mt-1 text-xs text-zinc-500">Связка CRM и стадия сделки</p>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <PlatformCard
          title="amoCRM"
          linkage={crm.amocrm}
          accentClass="text-sky-300"
        />
        <PlatformCard
          title="Bitrix24"
          linkage={crm.bitrix24}
          accentClass="text-orange-300"
        />

        {!hasConnectedPlatform ? (
          <p className="rounded-xl border border-dashed border-zinc-800 px-3 py-4 text-center text-xs text-zinc-500">
            CRM не подключена для этого агента. Настройте интеграцию в разделе CRM.
          </p>
        ) : null}
      </div>

      {hasConnectedPlatform && !hasLinkedDeal && onCreateDeal ? (
        <button
          type="button"
          onClick={onCreateDeal}
          disabled={creating}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3 py-2.5 text-sm font-medium text-violet-200 transition hover:bg-violet-500/15 disabled:opacity-50"
        >
          {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Создать сделку в CRM
        </button>
      ) : null}
    </div>
  );
}
