"use client";

import { Draggable } from "@hello-pangea/dnd";
import { GripVertical } from "lucide-react";
import Link from "next/link";

import type { CrmDeal } from "@/lib/crm/types";
import { cn } from "@/lib/utils";

function formatAmount(amount: string | number, currency: string): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: currency || "KZT",
    maximumFractionDigits: 0,
  }).format(value);
}

function contactLabel(deal: CrmDeal): string | null {
  const contact = deal.contact;
  if (!contact) return null;
  const name = `${contact.first_name || ""} ${contact.last_name || ""}`.trim();
  return name || contact.phone || contact.email || null;
}

interface DealCardProps {
  deal: CrmDeal;
  index: number;
}

export function DealCard({ deal, index }: DealCardProps) {
  const contact = contactLabel(deal);

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
              {deal.title}
            </h3>
            <p className="text-sm font-medium text-emerald-300/90">
              {formatAmount(deal.amount, deal.currency)}
            </p>
            {contact ? (
              <p className="truncate text-xs text-zinc-400">{contact}</p>
            ) : (
              <p className="text-xs text-zinc-600">Без контакта</p>
            )}
          </Link>
        </article>
      )}
    </Draggable>
  );
}
