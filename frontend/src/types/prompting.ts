export interface PromptingContextVisibility {
  show_username_visibility: boolean;
  show_datetime_visibility: boolean;
  show_messenger_visibility: boolean;
}

export interface PromptingModelConfig {
  llm_model_name: string;
  llm_temperature: number;
}

export interface EnhancePromptRequest {
  prompt_instructions: string;
}

export interface EnhancePromptResponse {
  bot_id: string;
  enhanced_prompt: string;
  message: string;
}

export interface PromptingWorkspaceState {
  prompt_instructions: string;
  model: PromptingModelConfig;
  visibility: PromptingContextVisibility;
}

export const DEFAULT_PROMPTING_VISIBILITY: PromptingContextVisibility = {
  show_username_visibility: false,
  show_datetime_visibility: false,
  show_messenger_visibility: false,
};

export const PROMPTING_CONTEXT_TOGGLES: Array<{
  key: keyof PromptingContextVisibility;
  label: string;
  description: string;
}> = [
  {
    key: "show_username_visibility",
    label: "Передавать имя и никнейм клиента",
    description: "Добавляет username и display name в system context.",
  },
  {
    key: "show_datetime_visibility",
    label: "Передавать текущую дату и время",
    description: "Инжектирует локальный timestamp агента в каждый LLM-запрос.",
  },
  {
    key: "show_messenger_visibility",
    label: "Передавать тип мессенджера",
    description: "Telegram, WhatsApp, Instagram, VK или Web Widget channel tag.",
  },
];

export function temperatureModeLabel(value: number): {
  title: string;
  description: string;
} {
  if (value <= 0.25) {
    return {
      title: "Strict RAG",
      description: "0.0–0.25 · детерминированные ответы, минимальная креативность.",
    };
  }
  if (value <= 0.6) {
    return {
      title: "Balanced Ops",
      description: "0.26–0.60 · баланс точности и гибкости для support-сценариев.",
    };
  }
  return {
    title: "Creative Automation",
    description: "0.61–1.0 · свободная генерация для brainstorming и upsell.",
  };
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => window.setTimeout(resolve, ms));
}

export async function revealPromptWithFade(
  text: string,
  onUpdate: (partial: string) => void,
): Promise<void> {
  const totalSteps = 48;
  const stepSize = Math.max(1, Math.ceil(text.length / totalSteps));

  onUpdate("");
  for (let index = 0; index <= text.length; index += stepSize) {
    onUpdate(text.slice(0, Math.min(index, text.length)));
    await sleep(18);
  }
  onUpdate(text);
}
