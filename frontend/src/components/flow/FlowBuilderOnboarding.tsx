"use client";

import { Workflow } from "lucide-react";

import { CreateAgentButton } from "@/components/layout/CreateAgentButton";

export function FlowBuilderOnboarding() {
  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col items-center justify-center p-8 text-center">
      <div className="max-w-md">
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-violet-500/10 ring-1 ring-violet-500/25">
          <Workflow className="h-8 w-8 text-violet-400" />
        </div>
        <h1 className="text-xl font-semibold text-zinc-100">Сначала создайте агента</h1>
        <p className="mt-3 text-sm leading-relaxed text-zinc-500">
          Конструктор сценариев доступен после создания ИИ-агента. Мы автоматически создадим профиль
          и откроем настройки — как в MoonAI.
        </p>
        <CreateAgentButton variant="button" label="Создать агента" className="mt-6" />
      </div>
    </div>
  );
}
