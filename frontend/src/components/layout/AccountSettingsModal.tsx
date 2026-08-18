"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Copy, Loader2, Save, Settings, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import { TIMEZONE_LABELS, TIMEZONE_OPTIONS } from "@/types/agent";

interface AccountSettingsModalProps {
  open: boolean;
  onClose: () => void;
}

const SETTINGS_TABS = [{ id: "general", label: "Общее" }] as const;

export function AccountSettingsModal({ open, onClose }: AccountSettingsModalProps) {
  const currentUser = useBotStore((state) => state.currentUser);
  const updateAccountProfile = useBotStore((state) => state.updateAccountProfile);
  const { showToast } = useToast();

  const [activeTab, setActiveTab] = useState<(typeof SETTINGS_TABS)[number]["id"]>("general");
  const [companyName, setCompanyName] = useState("");
  const [fullName, setFullName] = useState("");
  const [timezone, setTimezone] = useState("Asia/Almaty");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !currentUser) {
      return;
    }
    setCompanyName(currentUser.company_name);
    setFullName(currentUser.full_name);
    setTimezone(currentUser.timezone || "Asia/Almaty");
  }, [currentUser, open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !saving) {
        onClose();
      }
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open, saving]);

  const referralLink =
    typeof window !== "undefined" && currentUser
      ? `${window.location.origin}/join/${currentUser.id.slice(0, 8).toUpperCase()}`
      : "https://mp.ai/join/WORKSPACE";

  const handleSave = async (): Promise<void> => {
    setSaving(true);
    try {
      await updateAccountProfile({
        company_name: companyName.trim(),
        full_name: fullName.trim(),
        timezone,
      });
      showToast("Настройки аккаунта сохранены.", "success");
      onClose();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось сохранить настройки."), "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCopyReferral = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(referralLink);
      showToast("Реферальная ссылка скопирована.", "success");
    } catch {
      showToast("Не удалось скопировать ссылку.", "error");
    }
  };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0 bg-black/75 backdrop-blur-sm"
            onClick={() => {
              if (!saving) {
                onClose();
              }
            }}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            className="relative z-10 flex h-[min(640px,calc(100vh-2rem))] w-full max-w-4xl overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950/95 shadow-glow-purple backdrop-blur-xl"
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
          >
            <aside className="hidden w-56 shrink-0 border-r border-zinc-800/80 bg-black/30 p-4 md:block">
              <div className="mb-6 flex items-center gap-2 px-2">
                <Settings className="h-4 w-4 text-violet-400" />
                <p className="text-sm font-semibold text-zinc-100">Настройки</p>
              </div>
              <nav className="space-y-1">
                {SETTINGS_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      "relative w-full rounded-xl px-3 py-2.5 text-left text-sm transition",
                      activeTab === tab.id
                        ? "bg-violet-500/10 text-violet-200"
                        : "text-zinc-400 hover:bg-zinc-900/80 hover:text-zinc-200",
                    )}
                  >
                    {activeTab === tab.id ? (
                      <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-violet-500" />
                    ) : null}
                    {tab.label}
                  </button>
                ))}
              </nav>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-center justify-between border-b border-zinc-800/80 px-5 py-4">
                <div>
                  <h2 className="text-lg font-semibold text-zinc-50">Общие настройки</h2>
                  <p className="text-xs text-zinc-500">Профиль аккаунта и параметры workspace</p>
                </div>
                <button
                  type="button"
                  disabled={saving}
                  onClick={onClose}
                  className="rounded-lg border border-zinc-800 p-2 text-zinc-400 transition hover:bg-zinc-900 hover:text-zinc-200 disabled:opacity-50"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-5">
                <section className="mb-6 rounded-2xl border border-zinc-800/80 bg-black/20 p-4">
                  <p className="text-sm font-medium text-zinc-200">Реферальная программа</p>
                  <p className="mt-1 text-xs text-zinc-500">Реферальная ссылка</p>
                  <div className="mt-3 flex gap-2">
                    <input
                      readOnly
                      value={referralLink}
                      className="min-w-0 flex-1 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-300"
                    />
                    <button
                      type="button"
                      onClick={() => void handleCopyReferral()}
                      className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-zinc-800 text-zinc-300 hover:bg-zinc-900"
                      aria-label="Скопировать ссылку"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                  </div>
                </section>

                <section>
                  <p className="mb-4 text-sm font-medium text-zinc-200">Данные</p>
                  <div className="space-y-4">
                    <div>
                      <label htmlFor="account-company-name" className="text-xs text-zinc-500">
                        Название аккаунта
                      </label>
                      <input
                        id="account-company-name"
                        value={companyName}
                        onChange={(event) => setCompanyName(event.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label htmlFor="account-email" className="text-xs text-zinc-500">
                        Email
                      </label>
                      <input
                        id="account-email"
                        readOnly
                        value={currentUser?.email ?? ""}
                        className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2.5 text-sm text-zinc-500"
                      />
                    </div>
                    <div>
                      <label htmlFor="account-full-name" className="text-xs text-zinc-500">
                        Имя
                      </label>
                      <input
                        id="account-full-name"
                        value={fullName}
                        onChange={(event) => setFullName(event.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label htmlFor="account-timezone" className="text-xs text-zinc-500">
                        Часовой пояс
                      </label>
                      <select
                        id="account-timezone"
                        value={timezone}
                        onChange={(event) => setTimezone(event.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm text-zinc-100 focus:border-violet-500 focus:outline-none"
                      >
                        {TIMEZONE_OPTIONS.map((option) => (
                          <option key={option} value={option}>
                            {TIMEZONE_LABELS[option]}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </section>
              </div>

              <div className="border-t border-zinc-800/80 px-5 py-4">
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void handleSave()}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Сохранить
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
