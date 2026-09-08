"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

export const COOKIE_CONSENT_KEY = "mpai_cookie_consent_v1";

export type CookieConsentState = {
  essential: true;
  analytics: boolean;
  marketing: boolean;
  updatedAt: string;
};

export function readCookieConsent(): CookieConsentState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(COOKIE_CONSENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CookieConsentState;
    if (!parsed || parsed.essential !== true) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeCookieConsent(partial: Omit<CookieConsentState, "essential" | "updatedAt">) {
  const value: CookieConsentState = {
    essential: true,
    analytics: Boolean(partial.analytics),
    marketing: Boolean(partial.marketing),
    updatedAt: new Date().toISOString(),
  };
  window.localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify(value));
  window.dispatchEvent(new CustomEvent("mpai:cookie-consent", { detail: value }));
  return value;
}

export function CookieConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setVisible(readCookieConsent() === null);
  }, []);

  if (!visible) return null;

  const acceptEssential = () => {
    writeCookieConsent({ analytics: false, marketing: false });
    setVisible(false);
  };

  const acceptAll = () => {
    writeCookieConsent({ analytics: true, marketing: true });
    setVisible(false);
  };

  return (
    <div
      role="dialog"
      aria-labelledby="cookie-consent-title"
      aria-describedby="cookie-consent-desc"
      className="fixed inset-x-0 bottom-0 z-[100] border-t border-zinc-700/80 bg-[#0b0b0e]/95 p-4 shadow-2xl backdrop-blur-md"
    >
      <div className="mx-auto flex max-w-4xl flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="text-left">
          <p id="cookie-consent-title" className="text-sm font-semibold text-zinc-100">
            Файлы cookie и похожие технологии
          </p>
          <p id="cookie-consent-desc" className="mt-1 text-xs leading-5 text-zinc-400">
            Мы используем необходимые cookie для входа и безопасности. Аналитические и
            маркетинговые — только с вашего согласия. Подробнее:{" "}
            <Link href="/legal/cookies" className="text-zinc-200 underline underline-offset-2">
              Политика cookie
            </Link>
            ,{" "}
            <Link href="/privacy" className="text-zinc-200 underline underline-offset-2">
              Политика конфиденциальности
            </Link>
            .
          </p>
        </div>
        <div className="flex flex-shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={acceptEssential}
            className="rounded-xl border border-zinc-600 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
          >
            Только необходимые
          </button>
          <button
            type="button"
            onClick={acceptAll}
            className="rounded-xl bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-300"
          >
            Принять все
          </button>
        </div>
      </div>
    </div>
  );
}
