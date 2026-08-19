"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { AddCustomFieldModal } from "@/components/crm/DealCustomFieldsPanel";
import { CrmSubNav } from "@/components/crm/CrmSubNav";
import { useToast } from "@/hooks/useToast";
import { deleteCustomField, listCustomFields } from "@/lib/crm/api";
import type { CrmCustomFieldDefinition } from "@/lib/crm/types";
import { getApiErrorMessage } from "@/store/useBotStore";

export default function CrmFieldsSettingsPage() {
  const { showToast } = useToast();
  const [dealFields, setDealFields] = useState<CrmCustomFieldDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const defs = await listCustomFields("deal");
      setDealFields(defs.sort((a, b) => a.position - b.position));
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить поля."), "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const onDelete = async (field: CrmCustomFieldDefinition) => {
    if (!window.confirm(`Удалить поле «${field.label}»?`)) return;
    setDeletingId(field.id);
    try {
      await deleteCustomField(field.id);
      setDealFields((prev) => prev.filter((item) => item.id !== field.id));
      showToast("Поле удалено.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось удалить поле."), "error");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6">
      <CrmSubNav />
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-50">Поля сделок</h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-500">
            Настройка пользовательских полей CRM — аналог раздела «Настройки → CRM → Поля» в
            Bitrix24. Созданные поля доступны во всех карточках сделок.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500"
        >
          <Plus className="h-4 w-4" />
          Добавить поле
        </button>
      </header>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка…
        </div>
      ) : dealFields.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-700 px-6 py-16 text-center">
          <p className="text-sm text-zinc-400">Пользовательских полей пока нет.</p>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="mt-4 text-sm text-violet-300 hover:text-violet-200"
          >
            Создать первое поле
          </button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-zinc-800/90">
          <table className="min-w-full text-sm">
            <thead className="bg-zinc-900/80 text-left text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Код</th>
                <th className="px-4 py-3">Тип</th>
                <th className="px-4 py-3 w-16" />
              </tr>
            </thead>
            <tbody>
              {dealFields.map((field) => (
                <tr key={field.id} className="border-t border-zinc-800/80">
                  <td className="px-4 py-3 font-medium text-zinc-100">{field.label}</td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-400">{field.field_key}</td>
                  <td className="px-4 py-3 text-zinc-300">{field.field_type}</td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      disabled={deletingId === field.id}
                      onClick={() => void onDelete(field)}
                      className="rounded p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-300"
                    >
                      {deletingId === field.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <AddCustomFieldModal
        open={addOpen}
        entityType="deal"
        nextPosition={dealFields.length}
        onClose={() => setAddOpen(false)}
        onCreated={(field) => {
          setDealFields((prev) => [...prev, field].sort((a, b) => a.position - b.position));
        }}
      />
    </div>
  );
}
