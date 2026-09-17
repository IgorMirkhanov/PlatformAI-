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

/** Fixed column width — shorter than full content, but normal text scale (MoonAI-like). */
const LIST_WIDTH = "w-full max-w-[720px]";

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
        <div
          className={cn(
            LIST_WIDTH,
            "rounded-2xl border border-dashed border-zinc-700 bg-[var(--card)] px-6 py-12 text-center text-sm text-[var(--canvas-muted)]",
          )}
        >
          Функций пока нет. Нажмите «+», чтобы создать первую.
        </div>
      ) : (
        <div className={cn(LIST_WIDTH, "grid gap-2.5")}>
          {functions.map((item) => (
            <div
              key={item.id}
              className={cn(
                "group flex items-center gap-3.5 rounded-2xl border border-zinc-700/80",
                "bg-[#141416] px-4 py-3.5 transition hover:border-violet-500/40 hover:bg-[#17171b]",
              )}
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-400/35">
                <Braces className="h-4 w-4 text-violet-300" strokeWidth={2.25} />
              </div>
              <Link href={`/bots/${botId}/functions/${item.id}`} className="min-w-0 flex-1">
                <p className="truncate font-mono text-[15px] font-semibold leading-5 text-zinc-50">
                  {item.name}
                </p>
                <p className="mt-1 line-clamp-2 text-[13px] leading-5 text-zinc-400">
                  {item.description || "Условие вызова не задано"}
                </p>
              </Link>
              <div className="flex shrink-0 items-center justify-center pl-2">
                <Switch
                  checked={item.is_active}
                  isLoading={busyId === item.id}
                  onCheckedChange={(checked) => void handleToggle(item, checked)}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className={cn(LIST_WIDTH, "flex justify-center pt-2")}>
        <button
          type="button"
          disabled={profileSaving}
          onClick={() => void handleCreate()}
          aria-label="Добавить функцию"
          className={cn(
            "inline-flex h-12 w-12 items-center justify-center rounded-full",
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
