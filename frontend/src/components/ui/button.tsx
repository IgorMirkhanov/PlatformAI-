"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export type ButtonVariant = "default" | "destructive" | "outline" | "ghost" | "secondary";
export type ButtonSize = "default" | "sm" | "lg" | "icon";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  default:
    "bg-zinc-100 text-zinc-950 hover:bg-white disabled:bg-zinc-100 disabled:text-zinc-950/70",
  secondary:
    "bg-zinc-800 text-zinc-100 hover:bg-zinc-700 disabled:bg-zinc-800 disabled:text-zinc-100/70",
  destructive:
    "bg-red-600 text-white hover:bg-red-500 disabled:bg-red-600 disabled:text-white/80",
  outline:
    "border border-zinc-700 bg-transparent text-zinc-100 hover:bg-zinc-900 disabled:border-zinc-700 disabled:bg-transparent disabled:text-zinc-100/70",
  ghost:
    "bg-transparent text-zinc-300 hover:bg-zinc-900 hover:text-zinc-50 disabled:bg-transparent disabled:text-zinc-300/70",
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "h-10 px-4 py-2 text-sm",
  sm: "h-8 rounded-lg px-3 text-xs",
  lg: "h-11 rounded-xl px-6 text-base",
  icon: "h-10 w-10",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "default",
      size = "default",
      isLoading = false,
      disabled,
      children,
      type = "button",
      ...props
    },
    ref,
  ) => {
    const isDisabled = Boolean(disabled || isLoading);

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        aria-busy={isLoading || undefined}
        className={cn(
          "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-semibold transition",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40",
          "disabled:pointer-events-none disabled:cursor-not-allowed",
          // Keep full variant colors while loading (avoid washed-out opacity on the shell).
          isLoading ? "disabled:opacity-100" : "disabled:opacity-60",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...props}
      >
        <span className={cn("inline-flex items-center gap-2", isLoading && "opacity-0")}>
          {children}
        </span>
        {isLoading ? (
          <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            <span className="sr-only">Loading</span>
          </span>
        ) : null}
      </button>
    );
  },
);
Button.displayName = "Button";
