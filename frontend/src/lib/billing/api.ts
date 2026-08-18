/**
 * Workspace & Billing HTTP client — wallet, ledger, org members & invites.
 */

import { apiRequest } from "@/lib/api";
import type {
  BillingTransactionListResponse,
  OrgInviteCreated,
  OrgInviteListResponse,
  OrgInviteRole,
  OrganizationMembersResponse,
  WalletBalanceResponse,
} from "@/lib/billing/types";

export type {
  BillingTransaction,
  BillingTransactionListResponse,
  OrgInvite,
  OrgInviteCreated,
  OrgInviteListResponse,
  OrgInviteRole,
  OrganizationMembersResponse,
  WalletBalanceResponse,
} from "@/lib/billing/types";

export async function getWalletBalance(): Promise<WalletBalanceResponse> {
  return apiRequest<WalletBalanceResponse>("/api/v1/billing/wallet");
}

export async function getCreditTransactions(
  page = 1,
  limit = 20,
): Promise<BillingTransactionListResponse> {
  const offset = Math.max(0, (page - 1) * limit);
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiRequest<BillingTransactionListResponse>(
    `/api/v1/billing/transactions?${params.toString()}`,
  );
}

export async function getOrganizationMembers(): Promise<OrganizationMembersResponse> {
  return apiRequest<OrganizationMembersResponse>("/api/v1/organizations/members");
}

export async function getOrganizationInvites(): Promise<OrgInviteListResponse> {
  return apiRequest<OrgInviteListResponse>("/api/v1/organizations/invites");
}

export async function createInvite(
  email: string,
  role: OrgInviteRole,
): Promise<OrgInviteCreated> {
  return apiRequest<OrgInviteCreated>("/api/v1/organizations/invites", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export async function revokeInvite(inviteId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/organizations/invites/${inviteId}`, {
    method: "DELETE",
  });
}

export async function acceptOrganizationInvite(token: string): Promise<{
  organization_id: string;
  role: string;
  membership_id: string;
  email: string;
}> {
  return apiRequest("/api/v1/organizations/invites/accept", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}
