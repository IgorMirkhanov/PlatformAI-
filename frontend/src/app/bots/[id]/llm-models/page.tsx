import { redirect } from "next/navigation";

interface AgentLlmModelsRedirectProps {
  params: { id: string };
}

export default function AgentLlmModelsRedirectPage({ params }: AgentLlmModelsRedirectProps) {
  redirect(`/bots/${params.id}/llm-config`);
}
