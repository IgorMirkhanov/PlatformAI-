/** Pre-made agent use-case templates seeded on bot creation (backend + sandbox flow). */
export const AGENT_USE_CASE_TEMPLATES = [
  {
    id: "support_rag",
    label: "Техподдержка и RAG",
    description: "Стартовый сценарий поддержки с RAG-ориентированным промптом.",
  },
  {
    id: "sales_crm",
    label: "Отдел продаж & CRM",
    description: "Лидогенерация, квалификация и передача в CRM.",
  },
  {
    id: "empty",
    label: "Пустой шаблон",
    description: "Минимальный приветственный узел без отраслевой специализации.",
  },
] as const;

export type AgentUseCaseTemplateId = (typeof AGENT_USE_CASE_TEMPLATES)[number]["id"];

export interface CreateAgentPayload {
  name: string;
  use_case: AgentUseCaseTemplateId;
  platform_type?: "TELEGRAM" | "WHATSAPP";
}
