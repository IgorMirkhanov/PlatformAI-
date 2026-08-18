import { createBot } from "@/lib/api";
import type { CreateBotResponse } from "@/lib/api";
import type { AgentUseCaseTemplateId } from "@/types/agent-templates";

export const DEFAULT_NEW_AGENT_NAME = "Новый ИИ-Агент";

export interface ProvisionAgentResult {
  botId: string;
  createResponse: CreateBotResponse;
}

/** Create a bot via API with use-case template seeding; returns the new bot id. */
export async function provisionNewAgent(
  name: string = DEFAULT_NEW_AGENT_NAME,
  useCase: AgentUseCaseTemplateId = "empty",
): Promise<ProvisionAgentResult> {
  const createResponse = await createBot({
    name,
    platform_type: "TELEGRAM",
    use_case: useCase,
  });

  return {
    botId: createResponse.bot_id,
    createResponse,
  };
}
