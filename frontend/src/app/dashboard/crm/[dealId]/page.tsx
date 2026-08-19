"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Loader2, Tag, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { DealCustomFieldsPanel } from "@/components/crm/DealCustomFieldsPanel";
import { DealTimeline } from "@/components/crm/DealTimeline";
import { useToast } from "@/hooks/useToast";
import {
  addNote,
  attachDealTag,
  getDeal,
  getNotes,
  getTimeline,
  listCrmTags,
  listCustomFields,
  removeDealTag,
  updateDeal,
} from "@/lib/crm/api";
import type {
  CrmCustomFieldDefinition,
  CrmDeal,
  CrmNote,
  CrmTag,
  CrmTimelineEvent,
} from "@/lib/crm/types";
import { getApiErrorMessage } from "@/store/useBotStore";

function formatAmount(amount: string | number, currency: string): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: currency || "KZT",
    maximumFractionDigits: 0,
  }).format(value);
}

function contactName(deal: CrmDeal): string {
  const c = deal.contact;
  if (!c) return "Не привязан";
  const name = `${c.first_name || ""} ${c.last_name || ""}`.trim();
  return name || "Без имени";
}

function inferAttachedTagIds(events: CrmTimelineEvent[]): Set<string> {
  const attached = new Set<string>();
  const chronological = [...events].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  for (const event of chronological) {
    const tagId =
      typeof event.payload?.tag_id === "string" ? event.payload.tag_id : null;
    if (!tagId) continue;
    if (event.event_type === "tag_added") attached.add(tagId);
    if (event.event_type === "tag_removed") attached.delete(tagId);
  }
  return attached;
}

export default function CrmDealDetailPage() {
  const params = useParams<{ dealId: string }>();
  const dealId = params.dealId;
  const router = useRouter();
  const { showToast } = useToast();

  const [deal, setDeal] = useState<CrmDeal | null>(null);
  const [notes, setNotes] = useState<CrmNote[]>([]);
  const [events, setEvents] = useState<CrmTimelineEvent[]>([]);
  const [allTags, setAllTags] = useState<CrmTag[]>([]);
  const [attachedTagIds, setAttachedTagIds] = useState<Set<string>>(new Set());
  const [fieldDefs, setFieldDefs] = useState<CrmCustomFieldDefinition[]>([]);
  const [fieldDraft, setFieldDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [noteText, setNoteText] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingFields, setSavingFields] = useState(false);
  const [savingDealMeta, setSavingDealMeta] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [amountDraft, setAmountDraft] = useState("");
  const [tagBusy, setTagBusy] = useState<string | null>(null);

  const loadFeed = useCallback(async (id: string) => {
    const [nextNotes, nextEvents] = await Promise.all([
      getNotes(id),
      getTimeline(id),
    ]);
    setNotes(nextNotes);
    setEvents(nextEvents);
    setAttachedTagIds(inferAttachedTagIds(nextEvents));
  }, []);

  const loadAll = useCallback(async () => {
    if (!dealId) return;
    setLoading(true);
    try {
      const [nextDeal, tags, defs] = await Promise.all([
        getDeal(dealId),
        listCrmTags().catch(() => [] as CrmTag[]),
        listCustomFields("deal").catch(() => [] as CrmCustomFieldDefinition[]),
      ]);
      setDeal(nextDeal);
      setTitleDraft(nextDeal.title);
      setAmountDraft(String(nextDeal.amount ?? ""));
      setAllTags(tags);
      setFieldDefs(defs.sort((a, b) => a.position - b.position));
      const draft: Record<string, string> = {};
      for (const def of defs) {
        const raw = nextDeal.custom_fields?.[def.field_key];
        draft[def.field_key] = raw == null ? "" : String(raw);
      }
      setFieldDraft(draft);
      await loadFeed(dealId);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить сделку."), "error");
      setDeal(null);
    } finally {
      setLoading(false);
    }
  }, [dealId, loadFeed, showToast]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const attachedTags = useMemo(
    () => allTags.filter((tag) => attachedTagIds.has(tag.id)),
    [allTags, attachedTagIds],
  );
  const availableTags = useMemo(
    () => allTags.filter((tag) => !attachedTagIds.has(tag.id)),
    [allTags, attachedTagIds],
  );

  const onSubmitNote = async (event: FormEvent) => {
    event.preventDefault();
    if (!dealId || !noteText.trim() || saving) return;
    setSaving(true);
    try {
      const created = await addNote(dealId, noteText.trim());
      setNoteText("");
      setNotes((prev) => [created, ...prev.filter((n) => n.id !== created.id)]);
      const nextEvents = await getTimeline(dealId);
      setEvents(nextEvents);
      showToast("Заметка сохранена.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить заметку."), "error");
    } finally {
      setSaving(false);
    }
  };

  const onAttachTag = async (tagId: string) => {
    if (!dealId || tagBusy) return;
    setTagBusy(tagId);
    try {
      await attachDealTag(dealId, tagId);
      setAttachedTagIds((prev) => new Set([...Array.from(prev), tagId]));
      const nextEvents = await getTimeline(dealId);
      setEvents(nextEvents);
      setAttachedTagIds(inferAttachedTagIds(nextEvents));
      showToast("Тег добавлен.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось добавить тег."), "error");
    } finally {
      setTagBusy(null);
    }
  };

  const onRemoveTag = async (tagId: string) => {
    if (!dealId || tagBusy) return;
    setTagBusy(tagId);
    try {
      await removeDealTag(dealId, tagId);
      setAttachedTagIds((prev) => {
        const next = new Set(prev);
        next.delete(tagId);
        return next;
      });
      const nextEvents = await getTimeline(dealId);
      setEvents(nextEvents);
      setAttachedTagIds(inferAttachedTagIds(nextEvents));
      showToast("Тег удалён.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить тег."), "error");
    } finally {
      setTagBusy(null);
    }
  };

  const onSaveDealMeta = async () => {
    if (!dealId || !deal || savingDealMeta) return;
    setSavingDealMeta(true);
    try {
      const updated = await updateDeal(dealId, {
        title: titleDraft.trim() || deal.title,
        amount: amountDraft === "" ? deal.amount : Number(amountDraft),
      });
      setDeal(updated);
      setTitleDraft(updated.title);
      setAmountDraft(String(updated.amount ?? ""));
      showToast("Данные сделки обновлены.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить сделку."), "error");
    } finally {
      setSavingDealMeta(false);
    }
  };

  const onSaveCustomFields = async () => {
    if (!dealId || !deal || savingFields) return;
    setSavingFields(true);
    try {
      const custom_fields: Record<string, unknown> = {
        ...(deal.custom_fields || {}),
      };
      for (const def of fieldDefs) {
        const raw = fieldDraft[def.field_key] ?? "";
        if (def.field_type === "number") {
          custom_fields[def.field_key] = raw === "" ? null : Number(raw);
        } else if (def.field_type === "boolean") {
          custom_fields[def.field_key] = raw === "true";
        } else {
          custom_fields[def.field_key] = raw;
        }
      }
      const updated = await updateDeal(dealId, { custom_fields });
      setDeal(updated);
      showToast("Поля сохранены.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить поля."), "error");
    } finally {
      setSavingFields(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 p-6 text-sm text-zinc-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загрузка сделки…
      </div>
    );
  }

  if (!deal) {
    return (
      <div className="space-y-4 p-6">
        <CrmSubNav />
        <div className="rounded-2xl border border-dashed border-zinc-700 px-6 py-16 text-center">
          <p className="text-sm text-zinc-300">Сделка не найдена</p>
          <button
            type="button"
            onClick={() => router.push("/dashboard/crm")}
            className="mt-4 text-sm text-violet-300 hover:text-violet-200"
          >
            Вернуться к доске
          </button>
        </div>
      </div>
    );
  }

  const linkedClientId = deal.contact?.linked_client_id ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-2">
          <CrmSubNav />
          <button
            type="button"
            onClick={() => router.push("/dashboard/crm")}
            className="inline-flex items-center gap-1.5 text-xs text-zinc-500 transition hover:text-zinc-300"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            К канбану
          </button>
          <h1 className="text-2xl font-semibold text-zinc-50">{deal.title}</h1>
          <p className="text-xs text-zinc-500">
            Карточка сделки · лента активности слева, реквизиты и поля справа
          </p>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.85fr)]">
        <section className="flex min-h-0 flex-col gap-4 overflow-y-auto rounded-2xl border border-zinc-800/60 bg-zinc-950/30 p-4">
          <div className="flex gap-2 border-b border-zinc-800/80 pb-3 text-sm">
            <span className="rounded-lg bg-violet-500/15 px-3 py-1.5 font-medium text-violet-100">
              Лента
            </span>
            <span className="rounded-lg px-3 py-1.5 text-zinc-500">Комментарии</span>
            <span className="rounded-lg px-3 py-1.5 text-zinc-500">Задачи</span>
          </div>
          <form
            onSubmit={onSubmitNote}
            className="rounded-2xl border border-zinc-800/90 bg-zinc-950/50 p-4"
          >
            <label className="block text-sm font-medium text-zinc-200">
              Новая заметка
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                rows={4}
                placeholder="Что обсудили с клиентом?"
                className="mt-2 w-full resize-y rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-2.5 text-sm text-zinc-100 outline-none ring-violet-500/30 placeholder:text-zinc-600 focus:ring-2"
              />
            </label>
            <div className="mt-3 flex justify-end">
              <button
                type="submit"
                disabled={saving || !noteText.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Сохранить
              </button>
            </div>
          </form>

          <div>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
              Лента
            </h2>
            <DealTimeline notes={notes} events={events} />
          </div>
        </section>

        <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start">
          <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              О сделке
            </p>
            <label className="mt-3 block text-xs text-zinc-500">
              Название
              <input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm font-medium text-zinc-100 outline-none focus:border-violet-500/40"
              />
            </label>
            <label className="mt-3 block text-xs text-zinc-500">
              Сумма ({deal.currency})
              <input
                type="number"
                min="0"
                value={amountDraft}
                onChange={(e) => setAmountDraft(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40"
              />
            </label>
            <button
              type="button"
              onClick={() => void onSaveDealMeta()}
              disabled={savingDealMeta}
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
            >
              {savingDealMeta ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Сохранить
            </button>
            <dl className="mt-4 space-y-2 border-t border-zinc-800/80 pt-4 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Статус</dt>
                <dd className="font-medium capitalize text-zinc-200">{deal.status}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Этап воронки</dt>
                <dd className="text-right font-medium text-zinc-200">
                  {deal.stage?.name ?? "—"}
                </dd>
              </div>
              {deal.source ? (
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Источник</dt>
                  <dd className="text-zinc-200">{deal.source}</dd>
                </div>
              ) : null}
            </dl>
            <p className="mt-3 text-lg font-semibold text-emerald-300">
              {formatAmount(deal.amount, deal.currency)}
            </p>
          </div>

          <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              <Tag className="h-3.5 w-3.5" />
              Теги
            </div>
            <div className="flex flex-wrap gap-2">
              {attachedTags.length === 0 ? (
                <span className="text-xs text-zinc-500">Тегов нет</span>
              ) : (
                attachedTags.map((tag) => (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => void onRemoveTag(tag.id)}
                    disabled={tagBusy === tag.id}
                    className="inline-flex items-center gap-1 rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-200 hover:border-red-400/40"
                    style={tag.color ? { borderColor: tag.color } : undefined}
                    title="Удалить тег"
                  >
                    {tag.name}
                    <X className="h-3 w-3 text-zinc-500" />
                  </button>
                ))
              )}
            </div>
            {availableTags.length > 0 ? (
              <label className="mt-3 block text-xs text-zinc-500">
                Добавить тег
                <select
                  className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none"
                  defaultValue=""
                  onChange={(e) => {
                    const value = e.target.value;
                    e.target.value = "";
                    if (value) void onAttachTag(value);
                  }}
                >
                  <option value="" disabled>
                    Выберите тег…
                  </option>
                  {availableTags.map((tag) => (
                    <option key={tag.id} value={tag.id}>
                      {tag.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>

          <DealCustomFieldsPanel
            fieldDefs={fieldDefs}
            fieldDraft={fieldDraft}
            savingFields={savingFields}
            onDraftChange={(key, value) =>
              setFieldDraft((prev) => ({ ...prev, [key]: value }))
            }
            onSave={() => void onSaveCustomFields()}
            onFieldDefsChange={(defs) => {
              setFieldDefs(defs);
              setFieldDraft((prev) => {
                const next = { ...prev };
                for (const def of defs) {
                  if (next[def.field_key] === undefined) {
                    next[def.field_key] = "";
                  }
                }
                return next;
              });
            }}
          />

          <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Контакт</p>
            <p className="mt-2 text-lg font-semibold text-zinc-100">{contactName(deal)}</p>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Телефон</dt>
                <dd className="text-zinc-200">{deal.contact?.phone || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Email</dt>
                <dd className="truncate text-zinc-200">{deal.contact?.email || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Источник</dt>
                <dd className="text-zinc-200">{deal.contact?.source || "—"}</dd>
              </div>
            </dl>
            {linkedClientId ? (
              <Link
                href={`/inbox?clientId=${encodeURIComponent(linkedClientId)}`}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/70 px-3 py-2.5 text-sm font-medium text-zinc-100 transition hover:border-violet-500/50 hover:text-violet-100"
              >
                Перейти в чат
                <ExternalLink className="h-3.5 w-3.5" />
              </Link>
            ) : null}
          </div>
        </aside>
      </div>
    </div>
  );
}
