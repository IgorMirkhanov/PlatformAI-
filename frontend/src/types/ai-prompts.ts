export interface OptimizeAIPromptRequest {
  prompt_text: string;
  bot_task?: string | null;
}

export interface OptimizeAIPromptResponse {
  optimized_prompt: string;
  model_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  message: string;
}
