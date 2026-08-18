"use client";

import { cn } from "@/lib/utils";
import { temperatureModeLabel } from "@/types/prompting";

interface TemperatureSliderProps {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

export function TemperatureSlider({ value, onChange, disabled = false }: TemperatureSliderProps) {
  const mode = temperatureModeLabel(value);
  const percent = Math.round(value * 100);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-zinc-100">Temperature</p>
          <p className="text-[11px] text-zinc-500">0.0 Strict RAG → 1.0 Creative Automation</p>
        </div>
        <div className="rounded-lg border border-violet-500/25 bg-violet-500/10 px-2.5 py-1 font-mono text-sm text-violet-200">
          {value.toFixed(2)}
        </div>
      </div>

      <div className="relative">
        <div className="pointer-events-none absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-gradient-to-r from-sky-500/30 via-violet-500/40 to-amber-500/40" />
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          disabled={disabled}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className={cn(
            "relative z-10 w-full appearance-none bg-transparent",
            "[&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none",
            "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-violet-300",
            "[&::-webkit-slider-thumb]:bg-violet-500 [&::-webkit-slider-thumb]:shadow-glow-purple",
            "[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full",
            "[&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-violet-300 [&::-moz-range-thumb]:bg-violet-500",
            disabled && "opacity-50",
          )}
        />
      </div>

      <div className="flex justify-between text-[10px] uppercase tracking-wider text-zinc-600">
        <span>0.00</span>
        <span>{percent}% creative weight</span>
        <span>1.00</span>
      </div>

      <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/50 p-3">
        <p className="text-xs font-semibold text-zinc-200">{mode.title}</p>
        <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{mode.description}</p>
      </div>
    </div>
  );
}
