import type { SubscriptionPlanName } from "@/types/billing";

export interface OrganizationUsage {
  organization_id: string;
  organization_name: string;
  plan_name: SubscriptionPlanName;
  active_bots: number;
  active_bots_limit: number;
  team_slots_used: number;
  team_slots_limit: number;
  wallet_balance_kzt?: number;
  is_low_balance?: boolean;
  low_balance_threshold_kzt?: number;
}

export const PLAN_DISPLAY_LABEL: Record<SubscriptionPlanName, string> = {
  FREE: "Free",
  PRO: "Pro",
  ENTERPRISE: "Enterprise",
};
