/** Types for Workspace & Billing frontend client. */

import type {
  BillingTransaction,
  BillingTransactionListResponse as LegacyTxnList,
} from "@/types/billing";
import type { TeamMember, UserRole } from "@/types/team";

export type OrgInviteRole = "ADMIN" | "MEMBER" | "OPERATOR" | "PROMPT_ENGINEER";

export interface WalletBalanceResponse {
  organization_id: string;
  balance: number;
  currency: string;
  plan_balance_kzt?: number | null;
  message?: string;
}

export type BillingTransactionListResponse = LegacyTxnList;

export type { BillingTransaction };

export interface OrganizationMembersResponse {
  company_id: string;
  members: TeamMember[];
  pending_invitations: Array<{
    id: string;
    company_id: string;
    email: string;
    role: UserRole;
    expires_at: string;
    status: string;
    created_at: string;
  }>;
  total_members: number;
  total_pending: number;
}

export interface OrgInvite {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  expires_at: string;
  is_accepted: boolean;
  created_at: string;
  invited_by_id?: string | null;
}

export interface OrgInviteListResponse {
  items: OrgInvite[];
  total: number;
}

export interface OrgInviteCreated {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  expires_at: string;
  token: string;
  created_at: string;
}
