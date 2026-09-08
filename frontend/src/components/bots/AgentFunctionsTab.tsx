"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Braces, Plus } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import type { BotAgentProfile, FunctionToolDefinition } from "@/types/agent";

interface AgentFunctionsTabProps {
  botId: string;
  profile: BotAgentProfile;
}

function emptyFunction(): FunctionToolDefinition {
  return {
    id: crypto.randomUUID(),
    name: `fn_${Date.now().toString(36)}`,
    description: "",
    parameters: [],
    reaction_mode: "llm",
    reaction_text: "",
    integration: "none",
    result_integrations: [],
    result_fields: [],
    post_scenario: "continue",
    nested_function_id: null,
    disable_delayed_messages: false,
    is_active: true,
  };
}

export function AgentFunctionsTab({ botId, profile }: AgentFunctionsTabProps) {
  const router = useRouter();
  const saveAgentFunctions = useBotStore((state) => state.saveAgentFunctions);
  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();
  const functions = useMemo(
    () => profile.function_tools ?? [],
    [profile.function_tools],
  );
  const [busyId, setBusyId] = useState<string | null>(null);

  const persist = async (next: FunctionToolDefinition[]): Promise<void> => {
    await saveAgentFunctions(botId, { function_tools: next });
  };

  const handleCreate = async (): Promise<void> => {
    const created = emptyFunction();
    try {
      await persist([...functions, created]);
      router.push(`/bots/${botId}/functions/${created.id}`);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать функцию."), "error");
    }
  };

  const handleToggle = async (item: FunctionToolDefinition, isActive: boolean): Promise<void> => {
    setBusyId(item.id);
    try {
      await persist(
        functions.map((row) => (row.id === item.id ? { ...row, is_active: isActive } : row)),
      );
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить функцию."), "error");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--canvas-fg)]">Функции</h2>
        <p className="mt-1 text-sm text-[var(--canvas-muted)]">
          Инструменты агента для Function Calling — без IDE.
        </p>
      </div>

      {functions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[var(--canvas-border)] bg-[var(--card)] px-6 py-14 text-center text-sm text-[var(--canvas-muted)]">
          Функций пока нет. Нажмите «+», чтобы создать первую.
        </div>
      ) : (
        <div className="grid gap-3">
          {functions.map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-4 rounded-2xl border border-[var(--canvas-border)] bg-[var(--card)] px-5 py-4 shadow-soft"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/10 ring-1 ring-violet-500/25">
                <Braces className="h-5 w-5 text-violet-400" />
              </div>
              <Link href={`/bots/${botId}/functions/${item.id}`} className="min-w-0 flex-1">
                <p className="font-mono text-sm font-medium text-[var(--canvas-fg)]">{item.name}</p>
                <p className="mt-0.5 truncate text-xs text-[var(--canvas-muted)]">
                  {item.description || "Условие вызова не задано"}
                </p>
              </Link>
              <Switch
                checked={item.is_active}
                isLoading={busyId === item.id}
                onCheckedChange={(checked) => void handleToggle(item, checked)}
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex justify-center pt-2">
        <button
          type="button"
          disabled={profileSaving}
          onClick={() => void handleCreate()}
          aria-label="Добавить функцию"
          className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-violet-600 text-white shadow-glow-purple transition hover:bg-violet-500 disabled:opacity-50"
        >
          <Plus className="h-6 w-6" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
