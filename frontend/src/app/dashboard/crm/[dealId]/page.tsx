"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ExternalLink, Loader2, Tag, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { DealCustomFieldsPanel } from "@/components/crm/DealCustomFieldsPanel";
import { DealTimeline } from "@/components/crm/DealTimeline";
import { useToast } from "@/hooks/useToast";
import { fetchTeamMembers } from "@/lib/api";
import {
  addNote,
  attachDealTag,
  closeDeal,
  getContacts,
  getDeal,
  getNotes,
  getPipelines,
  getTimeline,
  listCrmTags,
  listCustomFields,
  moveDealStage,
  removeDealTag,
  updateDeal,
} from "@/lib/crm/api";
import type {
  CrmContact,
  CrmCustomFieldDefinition,
  CrmDeal,
  CrmNote,
  CrmStage,
  CrmTag,
  CrmTimelineEvent,
} from "@/lib/crm/types";
import type { TeamMember } from "@/types/team";
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
  const [stages, setStages] = useState<CrmStage[]>([]);
  const [stageBusy, setStageBusy] = useState(false);
  const [contactQuery, setContactQuery] = useState("");
  const [contactResults, setContactResults] = useState<CrmContact[]>([]);
  const [contactBusy, setContactBusy] = useState(false);
  const [closeBusy, setCloseBusy] = useState(false);
  const [managerId, setManagerId] = useState("");
  const [managers, setManagers] = useState<TeamMember[]>([]);

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
      const [nextDeal, tags, defs, pipelines, team] = await Promise.all([
        getDeal(dealId),
        listCrmTags().catch(() => [] as CrmTag[]),
        listCustomFields("deal").catch(() => [] as CrmCustomFieldDefinition[]),
        getPipelines().catch(() => []),
        fetchTeamMembers().catch(() => null),
      ]);
      setDeal(nextDeal);
      setTitleDraft(nextDeal.title);
      setAmountDraft(String(nextDeal.amount ?? ""));
      setManagerId(nextDeal.assigned_user_id || "");
      setManagers(team?.members ?? []);
      setAllTags(tags);
      setFieldDefs(defs.sort((a, b) => a.position - b.position));
      const pipeline = pipelines.find((item) => item.id === nextDeal.pipeline_id);
      setStages(
        [...(pipeline?.stages || [])].sort((a, b) => a.position - b.position),
      );
      const draft: Record<string, string> = {};
      for (const def of defs) {
        const raw = nextDeal.custom_fields?.[def.field_key];
        draft[def.field_key] = raw == null ? "" : String(raw);
      }
      // Prefill org phone field from WhatsApp/contact when empty.
      if (
        defs.some((def) => def.field_key === "phone") &&
        !(draft.phone || "").trim()
      ) {
        draft.phone = (nextDeal.contact?.phone || "").trim();
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

  const onChangeStage = async (stageId: string) => {
    if (!dealId || !deal || stageBusy || stageId === deal.stage_id) return;
    setStageBusy(true);
    try {
      const updated = await moveDealStage(dealId, stageId);
      setDeal(updated);
      showToast("Этап обновлён.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сменить этап."), "error");
    } finally {
      setStageBusy(false);
    }
  };

  const onSearchContacts = async (query: string) => {
    setContactQuery(query);
    if (query.trim().length < 1) {
      setContactResults([]);
      return;
    }
    try {
      const response = await getContacts(1, 8, query.trim());
      setContactResults(response.items);
    } catch {
      setContactResults([]);
    }
  };

  const onLinkContact = async (contactId: string | null) => {
    if (!dealId || !deal || contactBusy) return;
    setContactBusy(true);
    try {
      const updated = await updateDeal(dealId, { contact_id: contactId });
      setDeal(updated);
      setContactQuery("");
      setContactResults([]);
      showToast(contactId ? "Контакт привязан." : "Контакт отвязан.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось привязать контакт."), "error");
    } finally {
      setContactBusy(false);
    }
  };

  const onCloseDeal = async (status: "won" | "lost") => {
    if (!dealId || !deal || closeBusy || deal.status !== "open") return;
    setCloseBusy(true);
    try {
      const updated = await closeDeal(dealId, status);
      setDeal(updated);
      showToast(status === "won" ? "Сделка выиграна." : "Сделка проиграна.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось закрыть сделку."), "error");
    } finally {
      setCloseBusy(false);
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
      const updated = await updateDeal(dealId, {
        custom_fields,
        assigned_user_id: managerId || null,
      });
      setDeal(updated);
      setManagerId(updated.assigned_user_id || "");
      const draft: Record<string, string> = {};
      for (const def of fieldDefs) {
        const raw = updated.custom_fields?.[def.field_key];
        draft[def.field_key] = raw == null ? "" : String(raw);
      }
      setFieldDraft(draft);
      showToast("Поля организации сохранены.", "success");
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
          <DealCustomFieldsPanel
            title="Данные заказа"
            fieldDefs={fieldDefs}
            fieldDraft={fieldDraft}
            savingFields={savingFields}
            managerId={managerId}
            managers={managers.map((member) => ({
              id: member.id,
              label: member.full_name || member.email,
            }))}
            onManagerChange={setManagerId}
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
            <label className="mt-3 block text-xs text-zinc-500">
              Этап воронки
              <select
                value={deal.stage_id}
                disabled={stageBusy || deal.status !== "open" || stages.length === 0}
                onChange={(event) => void onChangeStage(event.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40 disabled:opacity-50"
              >
                {stages.length === 0 ? (
                  <option value={deal.stage_id}>{deal.stage?.name ?? "—"}</option>
                ) : (
                  stages.map((stage) => (
                    <option key={stage.id} value={stage.id}>
                      {stage.name}
                    </option>
                  ))
                )}
              </select>
            </label>
            <dl className="mt-4 space-y-2 border-t border-zinc-800/80 pt-4 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Статус</dt>
                <dd className="font-medium capitalize text-zinc-200">{deal.status}</dd>
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
            {deal.status === "open" ? (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  disabled={closeBusy}
                  onClick={() => void onCloseDeal("won")}
                  className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                >
                  Выиграна
                </button>
                <button
                  type="button"
                  disabled={closeBusy}
                  onClick={() => void onCloseDeal("lost")}
                  className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
                >
                  Проиграна
                </button>
              </div>
            ) : null}
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

          <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/60 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Контакт</p>
            <p className="mt-2 text-lg font-semibold text-zinc-100">{contactName(deal)}</p>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Телефон</dt>
                <dd className="text-zinc-200">
                  {fieldDraft.phone || deal.contact?.phone || "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Email</dt>
                <dd className="truncate text-zinc-200">{deal.contact?.email || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Источник</dt>
                <dd className="text-zinc-200">
                  {deal.contact?.source || deal.source || "—"}
                </dd>
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
            <label className="mt-4 block text-xs text-zinc-500">
              Привязать контакт
              <input
                value={contactQuery}
                onChange={(event) => void onSearchContacts(event.target.value)}
                placeholder="Имя, телефон или email"
                className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40"
              />
            </label>
            {contactResults.length > 0 ? (
              <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-950/80 p-1">
                {contactResults.map((contact) => {
                  const label =
                    `${contact.first_name || ""} ${contact.last_name || ""}`.trim() ||
                    contact.phone ||
                    contact.email ||
                    "Без имени";
                  return (
                    <li key={contact.id}>
                      <button
                        type="button"
                        disabled={contactBusy}
                        onClick={() => void onLinkContact(contact.id)}
                        className="w-full rounded-lg px-2.5 py-2 text-left text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
                      >
                        <span className="block font-medium">{label}</span>
                        <span className="block text-[11px] text-zinc-500">
                          {[contact.phone, contact.email, contact.source]
                            .filter(Boolean)
                            .join(" · ") || "Без данных"}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : null}
            {deal.contact_id ? (
              <button
                type="button"
                disabled={contactBusy}
                onClick={() => void onLinkContact(null)}
                className="mt-2 w-full rounded-xl border border-zinc-800 px-3 py-2 text-xs text-zinc-400 hover:border-rose-500/30 hover:text-rose-200 disabled:opacity-50"
              >
                Отвязать контакт
              </button>
            ) : null}
          </div>
        </aside>
      </div>
    </div>
  );
}
