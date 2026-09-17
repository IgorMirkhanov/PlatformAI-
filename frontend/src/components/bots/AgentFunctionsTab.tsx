"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Braces, Plus } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
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
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--canvas-fg)]">Функции</h2>
        <p className="mt-1 text-sm text-[var(--canvas-muted)]">
          Инструменты агента для Function Calling — без IDE.
        </p>
      </div>

      {functions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-700 bg-[var(--card)] px-6 py-12 text-center text-sm text-[var(--canvas-muted)]">
          Функций пока нет. Нажмите «+», чтобы создать первую.
        </div>
      ) : (
        <div className="grid gap-2">
          {functions.map((item) => (
            <div
              key={item.id}
              className={cn(
                "group flex items-center gap-3 rounded-xl border border-zinc-700/90",
                "bg-[#121214] px-3.5 py-2.5 transition hover:border-violet-500/40 hover:bg-[#16161a]",
              )}
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 ring-1 ring-violet-400/35">
                <Braces className="h-4 w-4 text-violet-300" />
              </div>
              <Link href={`/bots/${botId}/functions/${item.id}`} className="min-w-0 flex-1">
                <p className="truncate font-mono text-[13px] font-semibold leading-5 text-zinc-50">
                  {item.name}
                </p>
                <p className="mt-0.5 truncate text-[11px] leading-4 text-zinc-400">
                  {item.description || "Условие вызова не задано"}
                </p>
              </Link>
              <Switch
                checked={item.is_active}
                isLoading={busyId === item.id}
                onCheckedChange={(checked) => void handleToggle(item, checked)}
                className="h-6 w-11 data-[state=checked]:bg-violet-600 data-[state=unchecked]:bg-zinc-600"
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex justify-center pt-1">
        <button
          type="button"
          disabled={profileSaving}
          onClick={() => void handleCreate()}
          aria-label="Добавить функцию"
          className={cn(
            "inline-flex h-11 w-11 items-center justify-center rounded-full",
            "bg-violet-600 text-white shadow-[0_0_0_1px_rgba(139,92,246,0.45),0_8px_24px_rgba(124,58,237,0.35)]",
            "transition hover:bg-violet-500 hover:shadow-[0_0_0_1px_rgba(167,139,250,0.55),0_10px_28px_rgba(124,58,237,0.45)]",
            "disabled:opacity-50",
          )}
        >
          <Plus className="h-5 w-5" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
