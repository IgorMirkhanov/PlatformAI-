"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

import { endImpersonationSession, impersonateClientByEmail } from "@/lib/api";
import {
  beginImpersonationSession,
  clearImpersonationSession,
  getImpersonatedUserId,
  getImpersonationMeta,
  getOriginalAdminSnapshot,
  isImpersonating as readIsImpersonating,
  isImpersonationExpired,
  type ImpersonationMeta,
} from "@/lib/impersonation";
import { setPlatformRoleCookie } from "@/lib/auth/tokens";
import { useToast } from "@/hooks/useToast";
import { useBotStore } from "@/store/useBotStore";
import type { CurrentUser } from "@/types/team";

interface AuthContextValue {
  isImpersonating: boolean;
  impersonationMeta: ImpersonationMeta | null;
  startImpersonation: (email: string, password: string) => Promise<void>;
  exitImpersonation: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { showToast } = useToast();
  const currentUser = useBotStore((state) => state.currentUser);
  const activeCompanyId = useBotStore((state) => state.activeCompanyId);
  const setCurrentUser = useBotStore((state) => state.setCurrentUser);
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const clearWorkspaceCache = useBotStore((state) => state.clearWorkspaceCache);

  const [impersonationMeta, setImpersonationMeta] = useState<ImpersonationMeta | null>(null);
  const [isImpersonating, setIsImpersonating] = useState(false);
  const expiryHandledRef = useRef(false);

  useEffect(() => {
    setIsImpersonating(readIsImpersonating());
    setImpersonationMeta(getImpersonationMeta());
    // Ensure impersonated_user_id survives rehydrate after F5.
    const meta = getImpersonationMeta();
    if (meta?.impersonated_user_id || meta?.user_id) {
      // no-op read — keys already in localStorage via beginImpersonationSession
      void getImpersonatedUserId();
    }
  }, [currentUser?.id]);

  const restoreAdminSession = useCallback(async (opts?: { expired?: boolean }) => {
    const snapshot = clearImpersonationSession();
    clearWorkspaceCache();

    if (snapshot?.user) {
      setCurrentUser(snapshot.user);
      useBotStore.setState({
        activeCompanyId: snapshot.active_company_id ?? snapshot.user.company_id,
      });
      setPlatformRoleCookie(
        snapshot.user.is_superadmin
          ? "SUPERADMIN"
          : snapshot.user.is_support
            ? "SUPPORT"
            : "USER",
      );
    }

    setImpersonationMeta(null);
    setIsImpersonating(false);

    if (opts?.expired) {
      showToast("Impersonation session expired", "settings");
    }

    window.location.assign("/admin");
  }, [clearWorkspaceCache, setCurrentUser, showToast]);

  const exitImpersonation = useCallback(async () => {
    const meta = getImpersonationMeta();
    try {
      await endImpersonationSession({
        target_user_id: meta?.user_id ?? meta?.impersonated_user_id,
        email: meta?.email,
      });
    } catch {
      // Still restore admin session even if audit end fails.
    }
    await restoreAdminSession();
  }, [restoreAdminSession]);

  // Auto-cleanup when impersonation JWT / meta expires (incl. after F5).
  useEffect(() => {
    if (!isImpersonating) {
      expiryHandledRef.current = false;
      return;
    }

    const check = () => {
      if (expiryHandledRef.current) return;
      if (!isImpersonationExpired()) return;
      expiryHandledRef.current = true;
      void restoreAdminSession({ expired: true });
    };

    check();
    const timer = window.setInterval(check, 15_000);
    return () => window.clearInterval(timer);
  }, [isImpersonating, restoreAdminSession]);

  const startImpersonation = useCallback(
    async (email: string, password: string) => {
      if (!currentUser?.is_superadmin) {
        throw new Error("Только суперадмин может войти под клиентом через этот эндпоинт.");
      }
      if (!password.trim()) {
        throw new Error("Подтвердите пароль администратора перед имперсонацией.");
      }

      const response = await impersonateClientByEmail(email, password);

      beginImpersonationSession({
        adminUser: currentUser!,
        activeCompanyId: activeCompanyId ?? currentUser!.company_id,
        accessToken: response.access_token,
        meta: {
          email: response.impersonated_user_email,
          user_id: response.impersonated_user_id,
          impersonated_user_id: response.impersonated_user_id,
          full_name: response.impersonated_user_name || "",
          company_name: response.organization_name,
          impersonated_by: response.impersonated_by,
          expires_at: response.expires_at,
        },
      });

      const targetUser: CurrentUser = {
        id: response.impersonated_user_id,
        email: response.impersonated_user_email,
        full_name: response.impersonated_user_name || response.impersonated_user_email,
        company_name: response.organization_name,
        company_id: response.organization_id,
        role: (response.impersonated_user_role as CurrentUser["role"]) || "OWNER",
        timezone: currentUser!.timezone || "Asia/Almaty",
        is_superadmin: false,
        is_support: false,
        created_at: new Date().toISOString(),
      };

      clearWorkspaceCache();
      setCurrentUser(targetUser);
      useBotStore.setState({ activeCompanyId: response.organization_id });
      setImpersonationMeta(getImpersonationMeta());
      setIsImpersonating(true);
      expiryHandledRef.current = false;

      await loadCurrentUser();
      router.push("/dashboard");
      router.refresh();
    },
    [
      activeCompanyId,
      clearWorkspaceCache,
      currentUser,
      loadCurrentUser,
      router,
      setCurrentUser,
    ],
  );

  const value = useMemo(
    () => ({
      isImpersonating,
      impersonationMeta,
      startImpersonation,
      exitImpersonation,
    }),
    [exitImpersonation, impersonationMeta, isImpersonating, startImpersonation],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}

/** Safe hook for layouts that may render outside the provider during SSR. */
export function useAuthOptional(): AuthContextValue | null {
  return useContext(AuthContext);
}

export function useHasOriginalAdminToken(): boolean {
  const [flag, setFlag] = useState(false);
  useEffect(() => {
    setFlag(Boolean(getOriginalAdminSnapshot()));
  }, []);
  return flag;
}
