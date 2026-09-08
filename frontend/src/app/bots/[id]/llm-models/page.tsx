import { redirect } from "next/navigation";

interface AgentLlmModelsRedirectProps {
  params: Promise<{ id: string }>;
}

export default async function AgentLlmModelsRedirectPage({
  params,
}: AgentLlmModelsRedirectProps) {
  const { id } = await params;
  redirect(`/bots/${id}/llm-config`);
}
