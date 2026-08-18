"use client";

import { useCallback, useState } from "react";

import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage } from "@/store/useBotStore";

export interface UseAsyncActionOptions {
  /** Toast message on success. Pass `false` to skip. */
  successMessage?: string | false;
  /** Toast message on error (fallback if error has no message). */
  errorMessage?: string;
  /** Toast variant for success (defaults to success). */
  successVariant?: "success" | "info" | "settings" | "prompting" | "knowledge";
}

export interface AsyncActionResult<T> {
  ok: true;
  data: T;
}

export interface AsyncActionFailure {
  ok: false;
  error: unknown;
}

export type AsyncActionOutcome<T> = AsyncActionResult<T> | AsyncActionFailure;

/**
 * Standardize async UI actions (toggles, buttons) with loading + toast handling.
 */
export function useAsyncAction<TArgs extends unknown[] = [], TResult = void>(
  action: (...args: TArgs) => Promise<TResult>,
  options: UseAsyncActionOptions = {},
) {
  const { showToast } = useToast();
  const [isLoading, setIsLoading] = useState(false);

  const run = useCallback(
    async (...args: TArgs): Promise<AsyncActionOutcome<TResult>> => {
      setIsLoading(true);
      try {
        const data = await action(...args);
        if (options.successMessage !== false && options.successMessage) {
          showToast(options.successMessage, options.successVariant ?? "success");
        }
        return { ok: true, data };
      } catch (error) {
        showToast(
          getApiErrorMessage(error, options.errorMessage ?? "Action failed."),
          "error",
        );
        return { ok: false, error };
      } finally {
        setIsLoading(false);
      }
    },
    [action, options.errorMessage, options.successMessage, options.successVariant, showToast],
  );

  return { run, isLoading, isPending: isLoading };
}
