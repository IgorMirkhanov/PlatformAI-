"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Building2,
  Check,
  ChevronDown,
  Loader2,
  Plus,
  Search,
  X,
} from "lucide-react";

import { useOrganizationStore } from "@/lib/stores/use-organization-store";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage } from "@/store/useBotStore";
import { PLAN_BADGE_STYLES } from "@/types/billing";
import { PLAN_DISPLAY_LABEL } from "@/types/organization";

export function OrgSwitcher({ className }: { className?: string }) {
  const { showToast } = useToast();
  const containerRef = useRef<HTMLDivElement>(null);

  const organizations = useOrganizationStore((s) => s.organizations);
  const currentOrgId = useOrganizationStore((s) => s.currentOrgId);
  const planName = useOrganizationStore((s) => s.planName);
  const loading = useOrganizationStore((s) => s.loading);
  const switching = useOrganizationStore((s) => s.switching);
  const loadOrganizations = useOrganizationStore((s) => s.loadOrganizations);
  const loadUsage = useOrganizationStore((s) => s.loadUsage);
  const switchOrganization = useOrganizationStore((s) => s.switchOrganization);
  const createOrganization = useOrganizationStore((s) => s.createOrganization);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void loadOrganizations().then(() => loadUsage());
  }, [loadOrganizations, loadUsage]);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const currentOrg = useMemo(
    () =>
      organizations.find((org) => org.id === currentOrgId) ??
      organizations.find((org) => org.is_active) ??
      null,
    [organizations, currentOrgId],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return organizations;
    return organizations.filter((org) => org.name.toLowerCase().includes(q));
  }, [organizations, query]);

  const showSearch = organizations.length > 3;
  const plan = planName ?? "FREE";
  const planStyles = PLAN_BADGE_STYLES[plan];

  const handleSwitch = async (orgId: string) => {
    if (switching || orgId === currentOrgId) {
      setOpen(false);
      return;
    }
    try {
      setOpen(false);
      await switchOrganization(orgId);
      showToast("Workspace switched.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to switch organization."), "error");
    }
  };

  const handleCreate = async () => {
    const trimmed = newName.trim();
    if (!trimmed) {
      showToast("Enter an organization name.", "error");
      return;
    }
    setCreating(true);
    try {
      await createOrganization(trimmed);
      setCreateOpen(false);
      setNewName("");
      showToast("Organization created.", "success");
    } catch (error) {
      showToast(getApiErrorMessage(error, "Failed to create organization."), "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <div ref={containerRef} className={cn("relative", className)}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          disabled={switching}
          className="flex max-w-[16rem] items-center gap-2 rounded-xl border border-zinc-800/80 bg-zinc-950/70 px-3 py-2 text-left transition hover:border-zinc-700 hover:bg-zinc-900/80 disabled:opacity-60"
        >
          <Building2 className="h-4 w-4 shrink-0 text-violet-300" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-zinc-100">
              {currentOrg?.name ?? "Select workspace"}
            </p>
            <span
              className={cn(
                "mt-0.5 inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
                planStyles.badge,
              )}
            >
              {PLAN_DISPLAY_LABEL[plan]}
            </span>
          </div>
          {switching || loading ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-violet-300" />
          ) : (
            <ChevronDown
              className={cn("h-4 w-4 shrink-0 text-zinc-500 transition", open && "rotate-180")}
            />
          )}
        </button>

        <AnimatePresence>
          {open ? (
            <motion.div
              initial={{ opacity: 0, y: 6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 4, scale: 0.98 }}
              transition={{ duration: 0.16 }}
              className="absolute left-0 top-[calc(100%+0.4rem)] z-50 w-80 overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950/95 shadow-xl backdrop-blur-xl"
            >
              <div className="border-b border-zinc-800/80 px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-600">
                  Workspaces
                </p>
              </div>

              {showSearch ? (
                <div className="border-b border-zinc-800/60 px-3 py-2">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search organizations…"
                      className="w-full rounded-lg border border-zinc-800 bg-zinc-900/80 py-1.5 pl-8 pr-2 text-xs text-zinc-100 outline-none focus:border-zinc-600"
                    />
                  </div>
                </div>
              ) : null}

              <div className="max-h-56 overflow-y-auto p-1.5">
                {loading ? (
                  <div className="flex justify-center py-6">
                    <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
                  </div>
                ) : filtered.length === 0 ? (
                  <p className="px-2 py-4 text-center text-xs text-zinc-500">No organizations</p>
                ) : (
                  filtered.map((org) => {
                    const active = org.id === (currentOrgId ?? currentOrg?.id);
                    return (
                      <button
                        key={org.id}
                        type="button"
                        onClick={() => void handleSwitch(org.id)}
                        disabled={switching}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition",
                          active
                            ? "bg-violet-500/10 text-violet-100"
                            : "text-zinc-300 hover:bg-zinc-900",
                        )}
                      >
                        <Building2 className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                        <span className="min-w-0 flex-1 truncate">{org.name}</span>
                        {active ? <Check className="h-3.5 w-3.5 text-violet-300" /> : null}
                        {switching && org.id === currentOrgId ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : null}
                      </button>
                    );
                  })
                )}
              </div>

              <div className="border-t border-zinc-800/80 p-2">
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    setCreateOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-sm text-violet-300 transition hover:bg-violet-500/10"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Create New Organization
                </button>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {createOpen ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm"
            onClick={() => !creating && setCreateOpen(false)}
          >
            <motion.div
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-zinc-50">Create organization</h2>
                  <p className="mt-1 text-sm text-zinc-500">
                    Spin up a new workspace with its own bots, team, and billing context.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setCreateOpen(false)}
                  disabled={creating}
                  className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <label className="mt-5 block space-y-1.5">
                <span className="text-xs font-medium text-zinc-400">Organization name</span>
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleCreate();
                  }}
                  placeholder="Acme Support"
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-zinc-600"
                />
              </label>

              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setCreateOpen(false)}
                  disabled={creating}
                  className="rounded-xl border border-zinc-800 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-900"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void handleCreate()}
                  disabled={creating}
                  className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  Create
                </button>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
}
