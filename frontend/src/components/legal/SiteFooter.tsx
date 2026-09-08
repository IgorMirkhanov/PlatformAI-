"use client";

import Link from "next/link";

import { COMPANY } from "@/lib/company";
import { SUPPORT_EMAIL } from "@/lib/support-email";

const LINKS = [
  { href: "/privacy", label: "Конфиденциальность" },
  { href: "/terms", label: "Условия" },
  { href: "/legal/cookies", label: "Cookie" },
  { href: "/legal/personal-data", label: "ПДн" },
  { href: "/legal/refund", label: "Возвраты" },
  { href: "/support", label: "Поддержка" },
  { href: "/legal/limitations", label: "Ограничения" },
] as const;

export function SiteFooter({ className = "" }: { className?: string }) {
  return (
    <footer
      className={`border-t border-[#1f2430]/80 py-6 text-center text-xs text-zinc-500 ${className}`}
    >
      <p className="text-zinc-400">
        {COMPANY.brand} · {COMPANY.legalName} · {new Date().getFullYear()}
      </p>
      <p className="mt-1 text-[11px] text-zinc-500">
        БИН {COMPANY.bin} · {COMPANY.address}
      </p>
      <p className="mt-1">
        <a
          className="text-zinc-400 underline-offset-2 hover:text-zinc-200 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
          href={`mailto:${SUPPORT_EMAIL}`}
        >
          {SUPPORT_EMAIL}
        </a>
      </p>
      <nav
        aria-label="Юридические документы"
        className="mt-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-1"
      >
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
          >
            {link.label}
          </Link>
        ))}
      </nav>
      <p className="mx-auto mt-3 max-w-xl text-[10px] leading-4 text-zinc-600">
        Иконки интерфейса — Lucide (ISC). Стоковые фото на лендинге не используются. Метрики
        производительности на маркетинговых страницах носят ориентировочный характер и не
        являются гарантией SLA, если иное не указано в договоре.
      </p>
    </footer>
  );
}
