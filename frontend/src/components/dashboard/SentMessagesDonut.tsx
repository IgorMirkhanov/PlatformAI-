"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const COLORS = ["#6366f1", "#fbbf24", "#38bdf8", "#a78bfa", "#34d399", "#fb7185"];

interface SentMessagesDonutProps {
  total: number;
  agents: Array<{ name: string; value: number }>;
}

export function SentMessagesDonut({ total, agents }: SentMessagesDonutProps) {
  const data =
    agents.length > 0
      ? agents
      : [{ name: "Все", value: Math.max(total, 1) }];

  return (
    <div className="luxury-card h-full">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--canvas-fg)]">Отправленные сообщения</h3>
          <p className="text-xs text-[var(--canvas-muted)]">Распределение по агентам</p>
        </div>
        <span className="rounded-full border border-[var(--canvas-border)] px-2.5 py-1 text-[10px] uppercase tracking-wider text-[var(--canvas-muted)]">
          Все
        </span>
      </div>
      <div className="relative mx-auto h-64 w-full max-w-xs">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="88%"
              paddingAngle={2}
              stroke="none"
            >
              {data.map((entry, index) => (
                <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--card)",
                border: "1px solid var(--canvas-border)",
                borderRadius: 12,
                fontSize: 12,
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <p className="text-2xl font-semibold tabular-nums text-[var(--canvas-fg)]">{total}</p>
          <p className="text-xs text-[var(--canvas-muted)]">сообщений</p>
        </div>
      </div>
    </div>
  );
}
