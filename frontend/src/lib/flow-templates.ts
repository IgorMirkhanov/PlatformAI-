/** Seeded organization-flow graphs for the templates gallery. */
import type { FlowGraphEdge, FlowGraphNode } from "@/lib/flow/api";

export interface FlowTemplate {
  id: string;
  name: string;
  description: string;
  category: "support" | "sales" | "handoff" | "blank";
  nodes: FlowGraphNode[];
  edges: FlowGraphEdge[];
}

export const FLOW_TEMPLATES: FlowTemplate[] = [
  {
    id: "blank_trigger",
    name: "Пустой сценарий",
    description: "Только trigger. Соберите граф с нуля.",
    category: "blank",
    nodes: [
      {
        id: "trigger-1",
        type: "trigger",
        position: { x: 80, y: 160 },
        data: {
          label: "Trigger",
          trigger_type: "message_received",
          webhook_event: "",
        },
      },
    ],
    edges: [],
  },
  {
    id: "support_rag_flow",
    name: "Поддержка с RAG",
    description: "Входящее сообщение → поиск по базе знаний → ответ LLM.",
    category: "support",
    nodes: [
      {
        id: "trigger-1",
        type: "trigger",
        position: { x: 40, y: 180 },
        data: { label: "Сообщение", trigger_type: "message_received", webhook_event: "" },
      },
      {
        id: "rag-1",
        type: "knowledge_search",
        position: { x: 280, y: 180 },
        data: {
          label: "База знаний",
          top_k: 3,
          query_variable: "last_user_message",
          output_variable: "rag_context",
          knowledge_base_id: "",
        },
      },
      {
        id: "llm-1",
        type: "ai_agent",
        position: { x: 540, y: 180 },
        data: {
          label: "Ответ поддержки",
          prompt_context: "Отвечай кратко по фактам из rag_context. Если данных нет — скажи об этом.",
          knowledge_base_id: "",
          prompt_modifier: "",
        },
      },
    ],
    edges: [
      { id: "e-t-r", source: "trigger-1", target: "rag-1" },
      { id: "e-r-l", source: "rag-1", target: "llm-1" },
    ],
  },
  {
    id: "sales_crm_flow",
    name: "Квалификация лида",
    description: "Приветствие → квалификация LLM → запись в CRM.",
    category: "sales",
    nodes: [
      {
        id: "trigger-1",
        type: "trigger",
        position: { x: 40, y: 160 },
        data: { label: "Сообщение", trigger_type: "message_received", webhook_event: "" },
      },
      {
        id: "text-1",
        type: "text_message",
        position: { x: 280, y: 80 },
        data: {
          label: "Приветствие",
          text: "Здравствуйте! Я помогу подобрать решение. Расскажите, какая задача?",
          buttons: [],
        },
      },
      {
        id: "llm-1",
        type: "ai_agent",
        position: { x: 280, y: 260 },
        data: {
          label: "Квалификация",
          prompt_context: "Собери имя, компанию и потребность. Кратко резюмируй лид.",
          knowledge_base_id: "",
          prompt_modifier: "",
        },
      },
      {
        id: "crm-1",
        type: "crm_action",
        position: { x: 540, y: 260 },
        data: {
          label: "Создать сделку",
          action: "create_deal",
        },
      },
    ],
    edges: [
      { id: "e-t-txt", source: "trigger-1", target: "text-1" },
      { id: "e-txt-llm", source: "text-1", target: "llm-1" },
      { id: "e-llm-crm", source: "llm-1", target: "crm-1" },
    ],
  },
  {
    id: "handoff_flow",
    name: "Эскалация оператору",
    description: "LLM отвечает; при неуверенности — Human Handoff в inbox.",
    category: "handoff",
    nodes: [
      {
        id: "trigger-1",
        type: "trigger",
        position: { x: 40, y: 180 },
        data: { label: "Сообщение", trigger_type: "message_received", webhook_event: "" },
      },
      {
        id: "llm-1",
        type: "ai_agent",
        position: { x: 300, y: 180 },
        data: {
          label: "Первая линия",
          prompt_context: "Если не можешь помочь — попроси эскалацию.",
          knowledge_base_id: "",
          prompt_modifier: "",
        },
      },
      {
        id: "handoff-1",
        type: "human_handoff",
        position: { x: 560, y: 180 },
        data: {
          label: "Оператор",
          queue: "support",
        },
      },
    ],
    edges: [
      { id: "e-t-l", source: "trigger-1", target: "llm-1" },
      { id: "e-l-h", source: "llm-1", target: "handoff-1" },
    ],
  },
];
