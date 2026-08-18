import type { DashboardStatsResponse, DailyChartPoint } from "@/types/dashboard";

const DAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export const FALLBACK_DASHBOARD_STATS: DashboardStatsResponse = {
  total_unique_dialogs: 142,
  total_messages_dispatched: 3180,
  api_token_expenditure: 48.75,
  active_agents: 4,
  inactive_agents: 1,
  subscription_balance: 128.5,
  subscription_plan: "PRO",
  agents: [],
  period_label: "fallback",
};

export function buildDailyChartSeries(stats: DashboardStatsResponse): DailyChartPoint[] {
  const totalMessages = stats.total_messages_dispatched;
  const totalDialogs = stats.total_unique_dialogs;
  const weights = [0.72, 0.88, 0.95, 1.08, 1.15, 0.82, 0.9];

  return DAY_LABELS.map((label, index) => {
    const weight = weights[index] ?? 1;
    const messages = Math.max(0, Math.round((totalMessages / 7) * weight));
    const dialogs = Math.max(0, Math.round((totalDialogs / 7) * weight * 0.65));
    return { label, messages, dialogs };
  });
}

export function buildFallbackChartSeries(): DailyChartPoint[] {
  return buildDailyChartSeries(FALLBACK_DASHBOARD_STATS);
}

export function countActiveLeads(stats: DashboardStatsResponse): number {
  if (stats.agents.length > 0) {
    return stats.agents.reduce((sum, agent) => sum + agent.unique_dialogs, 0);
  }
  return stats.active_agents * 12 + stats.total_unique_dialogs;
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}
