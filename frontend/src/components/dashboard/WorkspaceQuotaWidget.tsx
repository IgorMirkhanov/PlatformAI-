"use client";

import { useEffect } from "react";

import { QuotaProgressBar } from "@/components/dashboard/QuotaProgressBar";
import { useOrganizationStore } from "@/lib/stores/use-organization-store";

/** Compact quota widget for the dashboard sidebar. */
export function WorkspaceQuotaWidget() {
  const usage = useOrganizationStore((s) => s.usage);
  const loadUsage = useOrganizationStore((s) => s.loadUsage);
  const currentOrgId = useOrganizationStore((s) => s.currentOrgId);

  useEffect(() => {
    void loadUsage();
  }, [loadUsage, currentOrgId]);

  if (!usage) return null;

  return (
    <QuotaProgressBar
      compact
      className="mt-3"
      metrics={[
        {
          label: "Active Bots",
          used: usage.active_bots,
          limit: usage.active_bots_limit,
        },
        {
          label: "Team Slots",
          used: usage.team_slots_used,
          limit: usage.team_slots_limit,
        },
      ]}
    />
  );
}
