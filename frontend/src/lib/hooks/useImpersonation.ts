"use client";

import { useAuthOptional } from "@/components/auth/AuthContext";
import {
  getImpersonationMeta,
  getOriginalAdminSnapshot,
  isImpersonating as readIsImpersonating,
  type ImpersonationMeta,
} from "@/lib/impersonation";

export function useImpersonation() {
  const auth = useAuthOptional();
  const meta: ImpersonationMeta | null =
    auth?.impersonationMeta ?? getImpersonationMeta();
  const isImpersonating = Boolean(
    auth?.isImpersonating || readIsImpersonating() || getOriginalAdminSnapshot(),
  );

  return {
    isImpersonating,
    meta,
    startImpersonation: auth?.startImpersonation,
    exitImpersonation: auth?.exitImpersonation,
  };
}
