"use client";

import { Loader2 } from "lucide-react";

import type { DealOrderDraft } from "@/lib/crm/orderFields";
import type { TeamMember } from "@/types/team";

interface DealOrderFieldsPanelProps {
  draft: DealOrderDraft;
  managerId: string;
  managers: TeamMember[];
  saving: boolean;
  onDraftChange: <K extends keyof DealOrderDraft>(
    key: K,
    value: DealOrderDraft[K],
  ) => void;
  onManagerChange: (userId: string) => void;
  onSave: () => void;
}

const inputClass =
  "mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500/40";

export function DealOrderFieldsPanel({
  draft,
  managerId,
  managers,
  saving,
  onDraftChange,
  onManagerChange,
  onSave,
}: DealOrderFieldsPanelProps) {
  return (
    <div className="rounded-2xl border border-zinc-800/90 bg-zinc-950/50 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Данные заказа
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-zinc-500 sm:col-span-2">
          Номер телефона
          <input
            type="tel"
            value={draft.phone}
            onChange={(e) => onDraftChange("phone", e.target.value)}
            placeholder="Подтягивается из WhatsApp"
            className={inputClass}
          />
        </label>
        <label className="block text-xs text-zinc-500 sm:col-span-2">
          Что заказали
          <textarea
            value={draft.ordered_items}
            onChange={(e) => onDraftChange("ordered_items", e.target.value)}
            rows={2}
            placeholder="Состав заказа"
            className={`${inputClass} resize-y`}
          />
        </label>
        <label className="block text-xs text-zinc-500">
          Дата заказа
          <input
            type="date"
            value={draft.order_date}
            onChange={(e) => onDraftChange("order_date", e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-xs text-zinc-500">
          Примерная дата изготовления
          <input
            type="date"
            value={draft.manufacturing_date}
            onChange={(e) => onDraftChange("manufacturing_date", e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-xs text-zinc-500 sm:col-span-2">
          Объект, где устанавливается
          <input
            type="text"
            value={draft.install_object}
            onChange={(e) => onDraftChange("install_object", e.target.value)}
            placeholder="Адрес или название объекта"
            className={inputClass}
          />
        </label>
        <label className="block text-xs text-zinc-500 sm:col-span-2">
          Сроки установки
          <input
            type="text"
            value={draft.install_deadline}
            onChange={(e) => onDraftChange("install_deadline", e.target.value)}
            placeholder="Например: 20–25 марта"
            className={inputClass}
          />
        </label>
        <label className="block text-xs text-zinc-500 sm:col-span-2">
          Ответственный менеджер
          <select
            value={managerId}
            onChange={(e) => onManagerChange(e.target.value)}
            className={inputClass}
          >
            <option value="">Не назначен</option>
            {managerId && !managers.some((m) => m.id === managerId) ? (
              <option value={managerId}>Назначенный менеджер</option>
            ) : null}
            {managers.map((member) => (
              <option key={member.id} value={member.id}>
                {member.full_name || member.email}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900 disabled:opacity-50 sm:w-auto"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Сохранить данные заказа
      </button>
    </div>
  );
}
