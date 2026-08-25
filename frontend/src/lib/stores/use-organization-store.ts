/**
 * Multi-tenant organization / workspace store.
 * Persists currentOrgId to localStorage + cookie for middleware / RSC.
 */

"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  createCompanyWorkspace,
  fetchOrganizationUsage,
  fetchOrganizations,
  switchCompanyWorkspace,
} from "@/lib/api";
import { setAccessToken } from "@/lib/auth/tokens";
import type { CompanyWorkspace } from "@/types/team";
import type { OrganizationUsage } from "@/types/organization";
import type { SubscriptionPlanName } from "@/types/billing";
import { useBotStore } from "@/store/useBotStore";

export const CURRENT_ORG_STORAGE_KEY = "mpai_current_org_id";
export const CURRENT_ORG_COOKIE = "mpai_org_id";

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function setOrgCookie(orgId: string | null): void {
  if (typeof document === "undefined") return;
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:" ? "; Secure" : "";
  if (!orgId) {
    document.cookie = `${CURRENT_ORG_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
    return;
  }
  document.cookie = `${CURRENT_ORG_COOKIE}=${encodeURIComponent(orgId)}; Path=/; Max-Age=${
    60 * 60 * 24 * 365
  }; SameSite=Lax${secure}`;
}

function writeOrgId(orgId: string | null): void {
  if (canUseStorage()) {
    if (orgId) {
      window.localStorage.setItem(CURRENT_ORG_STORAGE_KEY, orgId);
    } else {
      window.localStorage.removeItem(CURRENT_ORG_STORAGE_KEY);
    }
  }
  setOrgCookie(orgId);
}

function applyWorkspaceToken(accessToken: string | null | undefined): void {
  if (accessToken) {
    setAccessToken(accessToken);
  }
}

/** Soft cache invalidation after workspace switch (no SWR dependency yet). */
function invalidateWorkspaceCaches(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("mpai:organization-switched"));
}

interface OrganizationState {
  organizations: CompanyWorkspace[];
  currentOrgId: string | null;
  planName: SubscriptionPlanName | null;
  usage: OrganizationUsage | null;
  loading: boolean;
  switching: boolean;
  usageLoading: boolean;
  loadOrganizations: () => Promise<CompanyWorkspace[]>;
  loadUsage: () => Promise<OrganizationUsage | null>;
  setCurrentOrgId: (orgId: string | null) => void;
  switchOrganization: (orgId: string) => Promise<void>;
  createOrganization: (name: string) => Promise<CompanyWorkspace>;
  getCurrentOrganization: () => CompanyWorkspace | null;
}

export const useOrganizationStore = create<OrganizationState>()(
  persist(
    (set, get) => ({
      organizations: [],
      currentOrgId: null,
      planName: null,
      usage: null,
      loading: false,
      switching: false,
      usageLoading: false,

      setCurrentOrgId: (orgId) => {
        writeOrgId(orgId);
        set({ currentOrgId: orgId });
        useBotStore.setState({ activeCompanyId: orgId });
      },

      getCurrentOrganization: () => {
        const { organizations, currentOrgId } = get();
        if (!currentOrgId) return organizations.find((org) => org.is_active) ?? null;
        return organizations.find((org) => org.id === currentOrgId) ?? null;
      },

      loadOrganizations: async () => {
        set({ loading: true });
        try {
          const response = await fetchOrganizations();
          const organizations = Array.isArray(response.organizations) ? response.organizations : [];
          const currentOrgId = response.active_company_id;
          writeOrgId(currentOrgId);
          set({
            organizations,
            currentOrgId,
            loading: false,
          });
          useBotStore.setState({
            organizations,
            activeCompanyId: currentOrgId,
            organizationsLoading: false,
          });
          return organizations;
        } catch {
          set({ loading: false });
          return [];
        }
      },

      loadUsage: async () => {
        set({ usageLoading: true });
        try {
          const usage = await fetchOrganizationUsage();
          set({
            usage,
            planName: usage.plan_name,
            usageLoading: false,
          });
          return usage;
        } catch {
          set({ usageLoading: false });
          return null;
        }
      },

      switchOrganization: async (orgId) => {
        if (!orgId || orgId === get().currentOrgId) return;
        set({ switching: true });
        try {
          const response = await switchCompanyWorkspace({ company_id: orgId });
          applyWorkspaceToken(response.access_token);
          writeOrgId(response.company_id);

          const bot = useBotStore.getState();
          if (bot.currentUser) {
            useBotStore.setState({
              activeCompanyId: response.company_id,
              currentUser: {
                ...bot.currentUser,
                company_id: response.company_id,
                company_name: response.company_name,
                role: response.role,
                timezone: response.timezone,
              },
            });
          } else {
            useBotStore.setState({ activeCompanyId: response.company_id });
          }
          bot.clearWorkspaceCache();

          set({ currentOrgId: response.company_id, switching: false });
          await get().loadOrganizations();
          await get().loadUsage();
          invalidateWorkspaceCaches();

          // Hard reload ensures all tenant-scoped client state remounts cleanly.
          if (typeof window !== "undefined") {
            window.location.assign("/dashboard");
          }
        } catch (error) {
          set({ switching: false });
          throw error;
        }
      },

      createOrganization: async (name) => {
        const response = await createCompanyWorkspace({ name });
        applyWorkspaceToken(response.access_token);
        await get().switchOrganization(response.company.id);
        return response.company;
      },
    }),
    {
      name: "mpai-organization-store",
      partialize: (state) => ({
        currentOrgId: state.currentOrgId,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.currentOrgId) {
          writeOrgId(state.currentOrgId);
        }
      },
    },
  ),
);
