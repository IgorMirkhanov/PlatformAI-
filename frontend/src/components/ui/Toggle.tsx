"use client";

import { Info } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  isLoading?: boolean;
  label?: string;
  description?: string;
  hint?: string;
  className?: string;
}

export function Toggle({
  checked,
  onChange,
  disabled = false,
  isLoading = false,
  label,
  description,
  hint,
  className,
}: ToggleProps) {
  return (
    <div
      className={cn(
        "flex gap-4",
        label || description ? "items-start justify-between" : "items-center justify-center",
        className,
      )}
    >
      {(label || description) && (
        <div>
          {label && (
            <p className="flex items-center gap-1.5 text-sm font-medium text-zinc-100">
              {label}
              {hint && (
                <span title={hint} className="inline-flex text-zinc-500">
                  <Info className="h-3.5 w-3.5" />
                </span>
              )}
            </p>
          )}
          {description && (
            <p className="mt-1 text-xs leading-relaxed text-zinc-500">{description}</p>
          )}
        </div>
      )}
      <Switch
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        isLoading={isLoading}
        className="shrink-0"
      />
    </div>
  );
}
