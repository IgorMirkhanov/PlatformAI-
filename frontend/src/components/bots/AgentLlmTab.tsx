"use client";

import { useEffect, useMemo, useState } from "react";
import { Info } from "lucide-react";

import { SaveBar } from "@/components/bots/SaveBar";
import { Toggle } from "@/components/ui/Toggle";
import { fetchOrganizationApiKeys, upsertOrganizationApiKey } from "@/lib/api";
import { formatCurrency } from "@/lib/dashboard-utils";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import {
  LLM_MODEL_OPTIONS,
  type BotAgentProfile,
  type BotLlmExtras,
} from "@/types/agent";
import { LLM_API_KEY_PROVIDERS } from "@/types/organization-api-keys";
import { temperatureModeLabel } from "@/types/prompting";

interface AgentLlmTabProps {
  botId: string;
  profile: BotAgentProfile;
}

type SettingsMode = "standard" | "advanced";

const AUDIO_ENGINE_OPTIONS = [
  { id: "whisper", label: "Whisper (99+ языков)" },
  { id: "gpt4o_audio", label: "GPT-4o Audio" },
] as const;

const AUDIO_LANGUAGE_OPTIONS = [
  { id: "universal", label: "Универсальный" },
  { id: "ru", label: "Русский" },
  { id: "kk", label: "Қазақша" },
  { id: "en", label: "English" },
] as const;

function providerForModel(modelName: string): string {
  const lower = modelName.toLowerCase();
  if (lower.includes("claude") || lower.includes("anthropic")) return "anthropic";
  if (lower.includes("gemini") || lower.includes("google")) return "gemini";
  if (lower.includes("deepseek")) return "deepseek";
  return "openai";
}

export function AgentLlmTab({ botId, profile }: AgentLlmTabProps) {
  const saveAgentLlmConfig = useBotStore((state) => state.saveAgentLlmConfig);
  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);
  const { showToast } = useToast();

  const extras = profile.llm_extras ?? {};
  const [modelName, setModelName] = useState(profile.llm_model_name);
  const [temperature, setTemperature] = useState(profile.llm_temperature);
  const [settingsMode, setSettingsMode] = useState<SettingsMode>("standard");
  const [useCustomApiKey, setUseCustomApiKey] = useState(Boolean(extras.use_custom_api_key));
  const [customApiKey, setCustomApiKey] = useState("");
  const [maskedKey, setMaskedKey] = useState<string | null>(null);
  const [keyConfigured, setKeyConfigured] = useState(false);
  const [recognizeAudio, setRecognizeAudio] = useState(Boolean(extras.recognize_audio));
  const [recognizeImages, setRecognizeImages] = useState(Boolean(extras.recognize_images));
  const [recognizeFiles, setRecognizeFiles] = useState(Boolean(extras.recognize_files));
  const [audioEngine, setAudioEngine] = useState(extras.audio_engine || "whisper");
  const [audioLanguage, setAudioLanguage] = useState(extras.audio_language || "universal");
  const [maxTokens, setMaxTokens] = useState(Number(extras.max_tokens ?? 1000));
  const [topP, setTopP] = useState(Number(extras.top_p ?? 1));

  const selectedModel =
    LLM_MODEL_OPTIONS.find((option) => option.id === modelName) ?? LLM_MODEL_OPTIONS[0];
  const byokProvider = useMemo(() => providerForModel(modelName), [modelName]);
  const temperatureInfo = temperatureModeLabel(temperature);

  useEffect(() => {
    const next = profile.llm_extras ?? {};
    setModelName(profile.llm_model_name);
    setTemperature(profile.llm_temperature);
    setUseCustomApiKey(Boolean(next.use_custom_api_key));
    setRecognizeAudio(Boolean(next.recognize_audio));
    setRecognizeImages(Boolean(next.recognize_images));
    setRecognizeFiles(Boolean(next.recognize_files));
    setAudioEngine(next.audio_engine || "whisper");
    setAudioLanguage(next.audio_language || "universal");
    setMaxTokens(Number(next.max_tokens ?? 1000));
    setTopP(Number(next.top_p ?? 1));
  }, [profile]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetchOrganizationApiKeys();
        if (cancelled) return;
        const item = response.items.find((entry) => entry.provider === byokProvider);
        setKeyConfigured(Boolean(item?.configured && item.is_active));
        setMaskedKey(item?.masked_key ?? null);
        if (item?.configured && item.is_active && !profile.llm_extras?.use_custom_api_key) {
          setUseCustomApiKey(true);
        }
      } catch {
        if (!cancelled) {
          setKeyConfigured(false);
          setMaskedKey(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [byokProvider, profile.llm_extras?.use_custom_api_key]);

  const handleSave = async (): Promise<void> => {
    try {
      if (useCustomApiKey && !customApiKey.trim() && !keyConfigured) {
        showToast("Вставьте API-ключ провайдера или выключите BYOK.", "error");
        return;
      }
      if (useCustomApiKey && customApiKey.trim()) {
        const saved = await upsertOrganizationApiKey({
          provider: byokProvider,
          api_key: customApiKey.trim(),
          is_active: true,
        });
        setCustomApiKey("");
        setKeyConfigured(true);
        setMaskedKey(saved.masked_key);
      }

      const payloadExtras: BotLlmExtras = {
        use_custom_api_key: useCustomApiKey,
        recognize_audio: recognizeAudio,
        recognize_images: recognizeImages,
        recognize_files: recognizeFiles,
        audio_engine: audioEngine,
        audio_language: audioLanguage,
        max_tokens: maxTokens,
        top_p: topP,
      };

      await saveAgentLlmConfig(botId, {
        llm_model_name: modelName,
        llm_temperature: temperature,
        ...payloadExtras,
      });
      showToast("Конфигурация LLM сохранена.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить LLM."), "error");
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <section className="moonai-panel space-y-4">
        <div>
          <label htmlFor="llm-model" className="text-sm font-medium text-zinc-100">
            AI-движок
          </label>
          <select
            id="llm-model"
            value={modelName}
            onChange={(event) => setModelName(event.target.value)}
            className="mt-2 w-full rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-100"
          >
            {LLM_MODEL_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label} — {option.provider}
              </option>
            ))}
          </select>
        </div>
        <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/40 p-4">
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

      <section className="moonai-panel">
        <Toggle
          checked={useCustomApiKey}
          onChange={setUseCustomApiKey}
          label="Использовать свой API-ключ"
          description="При использовании собственного ключа токены не списываются с баланса платформы."
          hint="Ключ хранится в org BYOK vault и подставляется для выбранного провайдера модели."
        />
        {useCustomApiKey ? (
          <div className="mt-4 space-y-2">
            <p className="text-xs text-zinc-500">
              Провайдер:{" "}
              <span className="text-zinc-300">
                {LLM_API_KEY_PROVIDERS.find((item) => item.id === byokProvider)?.label ??
                  byokProvider}
              </span>
              {maskedKey ? (
                <span className="ml-2 font-mono text-zinc-400">текущий {maskedKey}</span>
              ) : null}
            </p>
            <input
              type="password"
              value={customApiKey}
              onChange={(event) => setCustomApiKey(event.target.value)}
              placeholder={keyConfigured ? "Новый ключ (оставьте пустым, чтобы не менять)" : "sk-..."}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 font-mono text-sm text-zinc-100"
            />
          </div>
        ) : null}
      </section>

      <section className="moonai-panel space-y-5">
        <div>
          <h2 className="text-base font-semibold text-zinc-50">Дополнительные настройки</h2>
          <div
            role="tablist"
            aria-label="Режим настроек LLM"
            className="mt-4 inline-flex rounded-xl border border-zinc-800 bg-zinc-950/60 p-1"
          >
            <button
              type="button"
              role="tab"
              id="llm-settings-trigger-standard"
              aria-selected={settingsMode === "standard"}
              aria-controls="llm-settings-content-standard"
              onClick={() => setSettingsMode("standard")}
              className={cn(
                "rounded-lg px-4 py-2 text-sm font-medium transition",
                settingsMode === "standard"
                  ? "bg-zinc-800 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200",
              )}
            >
              Стандартные настройки
            </button>
            <button
              type="button"
              role="tab"
              id="llm-settings-trigger-advanced"
              aria-selected={settingsMode === "advanced"}
              aria-controls="llm-settings-content-advanced"
              onClick={() => setSettingsMode("advanced")}
              className={cn(
                "rounded-lg px-4 py-2 text-sm font-medium transition",
                settingsMode === "advanced"
                  ? "bg-zinc-800 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200",
              )}
            >
              Продвинутые настройки
            </button>
          </div>
        </div>

        {settingsMode === "standard" ? (
          <div
            role="tabpanel"
            id="llm-settings-content-standard"
            aria-labelledby="llm-settings-trigger-standard"
            className="space-y-5"
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-zinc-100">Температура</p>
                <span className="font-mono text-sm text-violet-300">{temperature.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={temperature}
                onChange={(event) => setTemperature(Number(event.target.value))}
                className={cn(
                  "w-full appearance-none bg-transparent",
                  "[&::-webkit-slider-runnable-track]:h-2 [&::-webkit-slider-runnable-track]:rounded-full",
                  "[&::-webkit-slider-runnable-track]:bg-zinc-800",
                  "[&::-webkit-slider-thumb]:mt-[-4px] [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4",
                  "[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full",
                  "[&::-webkit-slider-thumb]:bg-violet-500 [&::-webkit-slider-thumb]:shadow-glow-purple",
                  "[&::-moz-range-track]:h-2 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-zinc-800",
                  "[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full",
                  "[&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-violet-500",
                )}
              />
              <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                <div>
                  <p className="text-sm font-medium text-emerald-300">{temperatureInfo.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-zinc-400">
                    {temperatureInfo.description}
                  </p>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div
            role="tabpanel"
            id="llm-settings-content-advanced"
            aria-labelledby="llm-settings-trigger-advanced"
            className="space-y-5"
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-zinc-100">Max tokens</p>
                  <p className="text-xs text-zinc-500">Лимит длины ответа модели.</p>
                </div>
                <span className="font-mono text-sm text-violet-300">{maxTokens}</span>
              </div>
              <input
                type="range"
                min={64}
                max={4096}
                step={64}
                value={maxTokens}
                onChange={(event) => setMaxTokens(Number(event.target.value))}
                className="w-full accent-violet-500"
              />
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-zinc-100">Top P</p>
                  <p className="text-xs text-zinc-500">Ограничение вероятностного ядра сэмплинга.</p>
                </div>
                <span className="font-mono text-sm text-violet-300">{topP.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={topP}
                onChange={(event) => setTopP(Number(event.target.value))}
                className="w-full accent-violet-500"
              />
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-zinc-100">Температура</p>
                <span className="font-mono text-sm text-violet-300">{temperature.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={temperature}
                onChange={(event) => setTemperature(Number(event.target.value))}
                className="w-full accent-violet-500"
              />
            </div>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="moonai-panel">
          <Toggle
            checked={recognizeAudio}
            onChange={setRecognizeAudio}
            label="Распознавать аудио"
            description="Включить распознавание аудио"
            hint="Голосовые и audio-вложения будут приниматься ботом."
          />
          {recognizeAudio ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <select
                value={audioEngine}
                onChange={(event) => setAudioEngine(event.target.value)}
                className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs text-zinc-200"
              >
                {AUDIO_ENGINE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select
                value={audioLanguage}
                onChange={(event) => setAudioLanguage(event.target.value)}
                className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs text-zinc-200"
              >
                {AUDIO_LANGUAGE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>

        <div className="moonai-panel">
          <Toggle
            checked={recognizeImages}
            onChange={setRecognizeImages}
            label="Распознавать изображения"
            description="Включить распознавание изображений"
            hint="Фото и картинки будут приниматься в диалоге."
          />
        </div>

        <div className="moonai-panel">
          <Toggle
            checked={recognizeFiles}
            onChange={setRecognizeFiles}
            label="Распознавать файлы"
            description="Включить распознавание файлов"
            hint="Документы и вложения-файлы будут приниматься ботом."
          />
        </div>
      </section>

      <SaveBar onSave={handleSave} saving={profileSaving} />
    </div>
  );
}
