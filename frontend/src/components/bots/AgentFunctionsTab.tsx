"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";

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
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-50">Функции</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Визуальный конструктор OpenAI Function Calling — без Python IDE.
          </p>
        </div>
        <button
          type="button"
          disabled={profileSaving}
          onClick={() => void handleCreate()}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Создать функцию
        </button>
      </div>

      {functions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-800 bg-[#0d0d0f] px-6 py-12 text-center text-sm text-zinc-500">
          Функций пока нет. Создайте первую — LLM получит её как tool.
        </div>
      ) : (
        <div className="grid gap-3">
          {functions.map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-zinc-800 bg-[#0d0d0f] px-5 py-4"
            >
              <Link href={`/bots/${botId}/functions/${item.id}`} className="min-w-0 flex-1">
                <p className="font-mono text-sm text-violet-200">{item.name}</p>
                <p className="mt-1 truncate text-xs text-zinc-500">
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
    </div>
  );
}
