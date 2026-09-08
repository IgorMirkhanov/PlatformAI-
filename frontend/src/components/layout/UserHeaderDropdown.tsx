"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  Building2,
  ChevronDown,
  CreditCard,
  CircleHelp,
  Loader2,
  LogOut,
  Plus,
  Settings,
  Sparkles,
} from "lucide-react";

import { AccountSettingsModal } from "@/components/layout/AccountSettingsModal";
import { useOrganizationStore } from "@/lib/stores/use-organization-store";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";

export function UserHeaderDropdown() {
  const router = useRouter();
  const { showToast } = useToast();
  const containerRef = useRef<HTMLDivElement>(null);

  const currentUser = useBotStore((state) => state.currentUser);
  const signOut = useBotStore((state) => state.signOut);

  const organizations = useOrganizationStore((state) => state.organizations);
  const activeCompanyId = useOrganizationStore((state) => state.currentOrgId);
  const organizationsLoading = useOrganizationStore((state) => state.loading);
  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations);
  const switchOrganization = useOrganizationStore((state) => state.switchOrganization);
  const createOrganization = useOrganizationStore((state) => state.createOrganization);

  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [creatingOrg, setCreatingOrg] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void loadOrganizations();
  }, [loadOrganizations]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent): void => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setCreatingOrg(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const activeOrg =
    organizations.find((org) => org.id === (activeCompanyId ?? currentUser?.company_id)) ??
    organizations.find((org) => org.is_active);

  const handleSwitch = async (companyId: string): Promise<void> => {
    if (switchingId || companyId === activeCompanyId) {
      setOpen(false);
      return;
    }
    setSwitchingId(companyId);
    try {
      await switchOrganization(companyId);
      showToast("Организация переключена.", "success");
      setOpen(false);
      router.refresh();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось переключить организацию."), "error");
    } finally {
      setSwitchingId(null);
    }
  };

  const handleCreateOrganization = async (): Promise<void> => {
    const trimmed = newOrgName.trim();
    if (!trimmed) {
      showToast("Укажите название организации.", "error");
      return;
    }
    setCreating(true);
    try {
      await createOrganization(trimmed);
      setNewOrgName("");
      setCreatingOrg(false);
      setOpen(false);
      showToast("Организация создана.", "success");
      router.push("/dashboard");
      router.refresh();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось создать организацию."), "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <div ref={containerRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex items-center gap-3 rounded-xl border border-zinc-800/80 bg-zinc-950/70 px-3 py-2 text-left transition hover:border-zinc-700 hover:bg-zinc-900/80"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-xs font-semibold text-violet-200 ring-1 ring-violet-500/30">
            {(activeOrg?.name ?? currentUser?.company_name ?? "MP")
              .trim()
              .slice(0, 2)
              .toUpperCase()}
          </div>
          <div className="hidden min-w-0 sm:block md:hidden">
            <p className="truncate text-sm font-medium text-zinc-100">
              {activeOrg?.name ?? currentUser?.company_name ?? "MP.AI Workspace"}
            </p>
            <p className="truncate text-[11px] text-zinc-500">
              {currentUser?.email ?? "admin@mp.ai"}
            </p>
          </div>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-zinc-500 transition",
              open && "rotate-180 text-violet-400",
            )}
          />
        </button>

        <AnimatePresence>
          {open ? (
            <motion.div
              initial={{ opacity: 0, y: 8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.98 }}
              transition={{ duration: 0.18, ease: "easeOut" }}
              className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-80 overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950/95 shadow-glow-purple backdrop-blur-xl"
            >
              <div className="border-b border-zinc-800/80 px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-600">
                  Организации
                </p>
              </div>

              <div className="max-h-52 overflow-y-auto p-2">
                {organizationsLoading ? (
                  <div className="flex items-center justify-center py-6 text-zinc-500">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                ) : organizations.length === 0 ? (
                  <p className="px-2 py-3 text-xs text-zinc-500">Организации не найдены</p>
                ) : (
                  organizations.map((org) => {
                    const isActive = org.id === (activeCompanyId ?? currentUser?.company_id);
                    return (
                      <button
                        key={org.id}
                        type="button"
                        disabled={Boolean(switchingId)}
                        onClick={() => void handleSwitch(org.id)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition",
                          isActive
                            ? "bg-violet-500/10 text-violet-100 ring-1 ring-violet-500/25"
                            : "text-zinc-300 hover:bg-zinc-900/80",
                        )}
                      >
                        <Building2 className="h-4 w-4 shrink-0 text-violet-400" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{org.name}</p>
                          <p className="text-[10px] text-zinc-500">{org.role}</p>
                        </div>
                        {switchingId === org.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />
                        ) : null}
                      </button>
                    );
                  })
                )}
              </div>

              <div className="border-t border-zinc-800/80 p-2">
                {creatingOrg ? (
                  <div className="space-y-2 rounded-xl border border-zinc-800 bg-black/30 p-3">
                    <input
                      value={newOrgName}
                      onChange={(event) => setNewOrgName(event.target.value)}
                      placeholder="Название организации"
                      className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={creating}
                        onClick={() => void handleCreateOrganization()}
                        className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-50"
                      >
                        {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                        Создать
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setCreatingOrg(false);
                          setNewOrgName("");
                        }}
                        className="rounded-lg border border-zinc-800 px-3 py-2 text-xs text-zinc-400 hover:bg-zinc-900"
                      >
                        Отмена
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setCreatingOrg(true)}
                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm text-violet-300 transition hover:bg-violet-500/10"
                  >
                    <Plus className="h-4 w-4" />
                    Создать организацию
                  </button>
                )}
              </div>

              <div className="border-t border-zinc-800/80 px-2 py-2">
                <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-600">
                  Аккаунт
                </p>
                <Link
                  href="/billing"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-300 transition hover:bg-zinc-900/80"
                >
                  <CreditCard className="h-4 w-4 text-violet-400" />
                  Подписки
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    setSettingsOpen(true);
                  }}
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-300 transition hover:bg-zinc-900/80"
                >
                  <Settings className="h-4 w-4 text-violet-400" />
                  Настройки
                </button>
                <Link
                  href="/dashboard/help"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-300 transition hover:bg-zinc-900/80"
                >
                  <CircleHelp className="h-4 w-4 text-violet-400" />
                  Справка
                </Link>
                <Link
                  href="/dashboard/settings/team"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-300 transition hover:bg-zinc-900/80"
                >
                  <Sparkles className="h-4 w-4 text-violet-400" />
                  Пользователи
                </Link>
              </div>

              <div className="border-t border-zinc-800/80 p-2">
                <button
                  type="button"
                  onClick={() => signOut()}
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-red-400 transition hover:bg-red-500/10"
                >
                  <LogOut className="h-4 w-4" />
                  Выйти
                </button>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      <AccountSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
