"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export interface SwitchProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  isLoading?: boolean;
}

export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  (
    {
      className,
      checked = false,
      onCheckedChange,
      isLoading = false,
      disabled,
      ...props
    },
    ref,
  ) => {
    const isDisabled = Boolean(disabled || isLoading);
    const state = checked ? "checked" : "unchecked";

    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        data-state={state}
        disabled={isDisabled}
        aria-busy={isLoading || undefined}
        onClick={() => {
          if (isDisabled) return;
          onCheckedChange?.(!checked);
        }}
        className={cn(
          "peer relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors duration-200",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950",
          "disabled:cursor-not-allowed disabled:opacity-60",
          "data-[state=checked]:bg-accent data-[state=unchecked]:bg-zinc-600",
          isLoading && "animate-pulse disabled:opacity-100",
          className,
        )}
        {...props}
      >
        <span
          data-state={state}
          className={cn(
            "pointer-events-none absolute top-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-white shadow-md transition-transform duration-200 ease-out",
            "data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0.5",
          )}
        >
          {isLoading ? (
            <Loader2 className="h-3 w-3 animate-spin text-zinc-700" aria-hidden />
          ) : null}
        </span>
        <span className="sr-only">{checked ? "On" : "Off"}</span>
      </button>
    );
  },
);
Switch.displayName = "Switch";
