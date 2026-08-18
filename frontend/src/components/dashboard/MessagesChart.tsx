"use client";

import { Download } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DailyChartPoint } from "@/types/dashboard";

interface MessagesChartProps {
  data: DailyChartPoint[];
  onExport?: () => void;
  exporting?: boolean;
}

export function MessagesChart({ data, onExport, exporting = false }: MessagesChartProps) {
  return (
    <div className="luxury-card h-full">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Отправки сообщений</h3>
          <p className="text-xs text-zinc-500">Динамика диспетчеризации за последние 7 дней</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-4 text-[10px] uppercase tracking-wider text-zinc-500">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-indigo-400" />
              Сообщения
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-violet-400" />
              Диалоги
            </span>
          </div>
          {onExport ? (
            <button
              type="button"
              onClick={onExport}
              disabled={exporting}
              className="inline-flex items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-xs font-medium text-violet-200 transition hover:bg-violet-500/20 disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5" />
              CSV отчёт
            </button>
          ) : null}
        </div>
      </div>

      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <defs>
              <linearGradient id="messagesGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="dialogsGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#27272a" strokeDasharray="4 4" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: "#71717a", fontSize: 11 }}
              axisLine={{ stroke: "#27272a" }}
              tickLine={false}
            />
            <YAxis tick={{ fill: "#71717a", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{
                background: "#121214",
                border: "1px solid #27272a",
                borderRadius: "12px",
                color: "#f4f4f5",
              }}
            />
            <Area
              type="monotone"
              dataKey="messages"
              stroke="#818cf8"
              strokeWidth={2.5}
              fill="url(#messagesGradient)"
            />
            <Area
              type="monotone"
              dataKey="dialogs"
              stroke="#a78bfa"
              strokeWidth={2}
              fill="url(#dialogsGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
