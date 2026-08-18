"use client";



import { useEffect, useState } from "react";



import { SaveBar } from "@/components/bots/SaveBar";

import { Toggle } from "@/components/ui/Toggle";

import { formatCurrency } from "@/lib/dashboard-utils";

import { cn } from "@/lib/utils";

import { useToast } from "@/hooks/useToast";

import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";

import { LLM_MODEL_OPTIONS, type BotAgentProfile } from "@/types/agent";



interface AgentLlmTabProps {

  botId: string;

  profile: BotAgentProfile;

}



export function AgentLlmTab({ botId, profile }: AgentLlmTabProps) {

  const saveAgentLlmConfig = useBotStore((state) => state.saveAgentLlmConfig);

  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);

  const { showToast } = useToast();



  const [modelName, setModelName] = useState(profile.llm_model_name);

  const [temperature, setTemperature] = useState(profile.llm_temperature);

  const [useCustomApiKey, setUseCustomApiKey] = useState(false);

  const [customApiKey, setCustomApiKey] = useState("");



  useEffect(() => {

    setModelName(profile.llm_model_name);

    setTemperature(profile.llm_temperature);

  }, [profile]);



  const selectedModel =

    LLM_MODEL_OPTIONS.find((option) => option.id === modelName) ?? LLM_MODEL_OPTIONS[0];



  const handleSave = async (): Promise<void> => {

    try {

      await saveAgentLlmConfig(botId, {

        llm_model_name: modelName,

        llm_temperature: temperature,

      });

      showToast("Конфигурация LLM сохранена.", "success");

    } catch (error) {

      showToast(getApiErrorMessage(error, "Не удалось сохранить LLM."), "error");

    }

  };



  return (

    <div className="space-y-6">

      <section className="glass-card">

        <label htmlFor="llm-model" className="text-xs text-zinc-500">

          AI-движок

        </label>

        <select

          id="llm-model"

          value={modelName}

          onChange={(event) => setModelName(event.target.value)}

          className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-sm text-zinc-100"

        >

          {LLM_MODEL_OPTIONS.map((option) => (

            <option key={option.id} value={option.id}>

              {option.label} — {option.provider}

            </option>

          ))}

        </select>



        <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">

          <p className="text-sm font-medium text-zinc-100">{selectedModel.label}</p>

          <p className="mt-1 text-xs text-zinc-500">{selectedModel.description}</p>

          <p className="mt-3 text-xs text-zinc-400">

            Стоимость:{" "}

            <span className="font-semibold text-emerald-400">

              {formatCurrency(selectedModel.costPer1kTokens)} / 1k токенов

            </span>

          </p>

        </div>

      </section>



      <section className="glass-card">

        <Toggle

          checked={useCustomApiKey}

          onChange={setUseCustomApiKey}

          label="Собственный API-ключ"

          description="Использовать ваши credentials провайдера (локальный preview в UI)."

        />

        {useCustomApiKey && (

          <input

            type="password"

            value={customApiKey}

            onChange={(event) => setCustomApiKey(event.target.value)}

            placeholder="sk-..."

            className="mt-4 w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 font-mono text-sm text-zinc-100"

          />

        )}

      </section>



      <section className="glass-card">

        <div className="mb-4 flex items-center justify-between gap-3">

          <div>

            <p className="text-sm font-medium text-zinc-100">Temperature</p>

            <p className="text-xs text-zinc-500">Креативность vs детерминизм (0.0 – 1.0).</p>

          </div>

          <span className={cn("font-mono text-sm text-indigo-300")}>{temperature.toFixed(2)}</span>

        </div>

        <input

          type="range"

          min={0}

          max={1}

          step={0.05}

          value={temperature}

          onChange={(event) => setTemperature(Number(event.target.value))}

          className="w-full accent-indigo-500"

        />

      </section>



      <SaveBar onSave={handleSave} saving={profileSaving} />

    </div>

  );

}


