export { CreateAgentModal } from "@/components/bots/CreateAgentModal";
export { AGENT_USE_CASE_TEMPLATES } from "@/types/agent-templates";
export type { AgentUseCaseTemplateId } from "@/types/agent-templates";

/** @deprecated Use AGENT_USE_CASE_TEMPLATES from @/types/agent-templates */
export const BUSINESS_CATEGORIES = [
  { id: "support_rag", label: "Техподдержка и RAG" },
  { id: "sales_crm", label: "Отдел продаж & CRM" },
  { id: "empty", label: "Пустой шаблон" },
] as const;

export type BusinessCategoryId = (typeof BUSINESS_CATEGORIES)[number]["id"];
