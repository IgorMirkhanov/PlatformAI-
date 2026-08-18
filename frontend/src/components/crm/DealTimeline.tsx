"use client";

import { useMemo } from "react";
import {
  ArrowRightLeft,
  GitBranch,
  MessageSquareText,
  Sparkles,
  Tag,
  Webhook,
} from "lucide-react";

import type { CrmNote, CrmTimelineEvent } from "@/lib/crm/types";
import { cn } from "@/lib/utils";

type FeedItem =
  | { kind: "note"; id: string; created_at: string; note: CrmNote }
  | { kind: "event"; id: string; created_at: string; event: CrmTimelineEvent };

const EVENT_LABELS: Record<string, string> = {
  deal_created: "Сделка создана",
  stage_changed: "Этап изменён",
  deal_closed: "Сделка закрыта",
  deal_updated: "Сделка обновлена",
  lead_captured: "Лид захвачен",
  tag_added: "Тег добавлен",
  tag_removed: "Тег удалён",
  note_added: "Заметка добавлена",
  webhook_sent: "Вебхук отправлен",
  automation_ran: "Автоматизация",
  field_changed: "Поле изменено",
};

type EventVisual = {
  label: string;
  Icon: typeof Sparkles;
  tone: string;
};

function eventVisual(eventType: string): EventVisual {
  switch (eventType) {
    case "note_added":
      return {
        label: "Заметка",
        Icon: MessageSquareText,
        tone: "border-violet-500/25 bg-violet-500/5 text-violet-300",
      };
    case "stage_changed":
      return {
        label: "Этап",
        Icon: GitBranch,
        tone: "border-amber-500/25 bg-amber-500/5 text-amber-300",
      };
    case "tag_added":
    case "tag_removed":
      return {
        label: "Тег",
        Icon: Tag,
        tone: "border-cyan-500/25 bg-cyan-500/5 text-cyan-300",
      };
    case "webhook_sent":
      return {
        label: "Вебхук",
        Icon: Webhook,
        tone: "border-sky-500/25 bg-sky-500/5 text-sky-300",
      };
    case "deal_closed":
    case "deal_created":
    case "deal_updated":
    case "field_changed":
      return {
        label: "Система",
        Icon: ArrowRightLeft,
        tone: "border-emerald-500/20 bg-emerald-500/5 text-emerald-300",
      };
    default:
      return {
        label: "Система",
        Icon: Sparkles,
        tone: "border-zinc-700 bg-zinc-950/60 text-zinc-400",
      };
  }
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function eventDescription(event: CrmTimelineEvent): string {
  const label = EVENT_LABELS[event.event_type] ?? event.event_type;
  const payload = event.payload || {};
  if (event.event_type === "stage_changed") {
    const from =
      typeof payload.from_stage_name === "string"
        ? payload.from_stage_name
        : typeof payload.from_stage_id === "string"
          ? payload.from_stage_id.slice(0, 8)
          : null;
    const to =
      typeof payload.to_stage_name === "string"
        ? payload.to_stage_name
        : typeof payload.to_stage_id === "string"
          ? payload.to_stage_id.slice(0, 8)
          : typeof payload.stage_name === "string"
            ? payload.stage_name
            : null;
    if (from && to) return `${label}: ${from} → ${to}`;
    if (to) return `${label}: ${to}`;
    return label;
  }
  if (event.event_type === "tag_added" || event.event_type === "tag_removed") {
    const name = typeof payload.tag_name === "string" ? payload.tag_name : null;
    return name ? `${label}: ${name}` : label;
  }
  if (event.event_type === "deal_closed") {
    const status = typeof payload.status === "string" ? payload.status : null;
    return status ? `${label} (${status})` : label;
  }
  if (event.event_type === "webhook_sent") {
    const url = typeof payload.url === "string" ? payload.url : null;
    return url ? `${label}: ${url}` : label;
  }
  return label;
}

interface DealTimelineProps {
  notes: CrmNote[];
  events: CrmTimelineEvent[];
}

export function DealTimeline({ notes, events }: DealTimelineProps) {
  const feed = useMemo(() => {
    const items: FeedItem[] = [
      ...notes.map((note) => ({
        kind: "note" as const,
        id: `note-${note.id}`,
        created_at: note.created_at,
        note,
      })),
      ...events
        .filter((event) => event.event_type !== "note_added")
        .map((event) => ({
          kind: "event" as const,
          id: `event-${event.id}`,
          created_at: event.created_at,
          event,
        })),
    ];
    return items.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  }, [notes, events]);

  if (feed.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-950/40 px-4 py-10 text-center text-sm text-zinc-500">
        История пока пуста. Добавьте первую заметку.
      </div>
    );
  }

  return (
    <ol className="space-y-3">
      {feed.map((item) => {
        if (item.kind === "note") {
          return (
            <li
              key={item.id}
              className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-4"
            >
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-violet-300/90">
                <MessageSquareText className="h-3.5 w-3.5" />
                Заметка оператора
                <span className="ml-auto font-normal normal-case tracking-normal text-zinc-500">
                  {formatWhen(item.created_at)}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">
                {item.note.text}
              </p>
            </li>
          );
        }

        const visual = eventVisual(item.event.event_type);
        const Icon = visual.Icon;
        return (
          <li key={item.id} className={cn("rounded-2xl border p-4", visual.tone)}>
            <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
              <Icon className="h-3.5 w-3.5" />
              {visual.label}
              <span className="ml-auto font-normal normal-case tracking-normal text-zinc-500">
                {formatWhen(item.created_at)}
              </span>
            </div>
            <p className="text-sm text-zinc-200">{eventDescription(item.event)}</p>
          </li>
        );
      })}
    </ol>
  );
}
