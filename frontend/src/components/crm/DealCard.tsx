"use client";

import { Draggable } from "@hello-pangea/dnd";
import { GripVertical } from "lucide-react";
import Link from "next/link";

import type { CrmDeal } from "@/lib/crm/types";
import { cn } from "@/lib/utils";

function leadName(deal: CrmDeal): string {
  const contact = deal.contact;
  if (contact) {
    const name = `${contact.first_name || ""} ${contact.last_name || ""}`.trim();
    if (name) return name;
  }
  return deal.title?.trim() || "Без имени";
}

function leadPhone(deal: CrmDeal): string | null {
  const fromFields =
    deal.custom_fields?.phone == null
      ? ""
      : String(deal.custom_fields.phone).trim();
  const fromContact = (deal.contact?.phone || "").trim();
  return fromFields || fromContact || null;
}

function formatLeadDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

interface DealCardProps {
  deal: CrmDeal;
  index: number;
  managerNames?: Record<string, string>;
}

export function DealCard({ deal, index, managerNames }: DealCardProps) {
  const name = leadName(deal);
  const phone = leadPhone(deal);
  const manager =
    (deal.assigned_user_id && managerNames?.[deal.assigned_user_id]) || null;
  const receivedAt = formatLeadDate(deal.created_at);

  return (
    <Draggable draggableId={deal.id} index={index}>
      {(provided, snapshot) => (
        <article
          ref={provided.innerRef}
          {...provided.draggableProps}
          className={cn(
            "group relative rounded-xl border border-zinc-800/90 bg-zinc-950/90 p-3 shadow-sm transition",
            snapshot.isDragging &&
              "border-violet-500/50 shadow-lg shadow-violet-950/40 ring-1 ring-violet-500/30",
          )}
        >
          <div
            {...provided.dragHandleProps}
            className="absolute right-2 top-2 cursor-grab rounded-md p-1 text-zinc-600 opacity-0 transition hover:bg-zinc-800 hover:text-zinc-300 group-hover:opacity-100 active:cursor-grabbing"
            aria-label="Перетащить сделку"
            title="Перетащить"
          >
            <GripVertical className="h-4 w-4" />
          </div>

          <Link
            href={`/dashboard/crm/${deal.id}`}
            className="block space-y-2 pr-6 outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
          >
            <h3 className="line-clamp-2 text-sm font-semibold text-zinc-100 transition group-hover:text-violet-100">
              {name}
            </h3>
            <dl className="space-y-1.5 text-xs">
              <div className="flex items-start justify-between gap-2">
                <dt className="shrink-0 text-zinc-500">Телефон</dt>
                <dd className="truncate text-right text-zinc-200">
                  {phone || "—"}
                </dd>
              </div>
              <div className="flex items-start justify-between gap-2">
                <dt className="shrink-0 text-zinc-500">Менеджер</dt>
                <dd className="truncate text-right text-zinc-200">
                  {manager || "Не назначен"}
                </dd>
              </div>
              <div className="flex items-start justify-between gap-2">
                <dt className="shrink-0 text-zinc-500">Поступил</dt>
                <dd className="truncate text-right text-zinc-300">{receivedAt}</dd>
              </div>
            </dl>
          </Link>
        </article>
      )}
    </Draggable>
  );
}
