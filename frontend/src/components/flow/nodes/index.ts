import type { NodeTypes } from "reactflow";

import { ApiRequestNode } from "./ApiRequestNode";
import { ConditionNode } from "./ConditionNode";
import { CrmNode, CRMNode } from "./CRMNode";
import { FlowHandle } from "./FlowHandle";
import { FlowNodeWrapper } from "./FlowNodeWrapper";
import { GoogleSheetsNode } from "./GoogleSheetsNode";
import { HumanHandoffNode } from "./HumanHandoffNode";
import { ImageGenerationNode } from "./ImageGenerationNode";
import { KnowledgeSearchNode } from "./KnowledgeSearchNode";
import { LLMNode } from "./LLMNode";
import { LoopNode } from "./LoopNode";
import { RAGNode } from "./RAGNode";
import { SqlQueryNode } from "./SqlQueryNode";
import { TextMessageNode } from "./TextMessageNode";
import { TriggerNode } from "./TriggerNode";
import { WhatsAppNode } from "./WhatsAppNode";

/** Product aliases */
export const APICallNode = ApiRequestNode;
export const CRMActionNode = CrmNode;

export const flowNodeTypes: NodeTypes = {
  trigger: TriggerNode,
  textMessage: TextMessageNode,
  whatsapp: WhatsAppNode,
  condition: ConditionNode,
  aiAgent: LLMNode,
  llm: LLMNode,
  knowledgeSearch: KnowledgeSearchNode,
  rag: RAGNode,
  apiRequest: ApiRequestNode,
  crmAction: CrmNode,
  crm: CrmNode,
  loop: LoopNode,
  humanHandoff: HumanHandoffNode,
  googleSheets: GoogleSheetsNode,
  sqlQuery: SqlQueryNode,
  imageGeneration: ImageGenerationNode,
};

export {
  ApiRequestNode,
  ConditionNode,
  CrmNode,
  CRMNode,
  FlowHandle,
  FlowNodeWrapper,
  GoogleSheetsNode,
  HumanHandoffNode,
  ImageGenerationNode,
  KnowledgeSearchNode,
  LLMNode,
  LoopNode,
  RAGNode,
  SqlQueryNode,
  TextMessageNode,
  TriggerNode,
  WhatsAppNode,
};
