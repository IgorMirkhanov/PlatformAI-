"use client";

import Link from "next/link";

const SUPPORT_EMAIL =
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL?.trim() || "support@example.com";

const LINKS = [
  { href: "/privacy", label: "Политика конфиденциальности" },
  { href: "/terms", label: "Условия использования" },
  { href: "/support", label: "Поддержка" },
  { href: "/legal/limitations", label: "Ограничения v1" },
] as const;

export function SiteFooter({ className = "" }: { className?: string }) {
  return (
    <footer
      className={`border-t border-[#1f2430]/80 py-6 text-center text-xs text-zinc-600 ${className}`}
    >
      <p>
        MP.AI · Production AI Platform · {new Date().getFullYear()} ·{" "}
        <a className="hover:text-zinc-400" href={`mailto:${SUPPORT_EMAIL}`}>
          {SUPPORT_EMAIL}
        </a>
      </p>
      <nav className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
        {LINKS.map((link) => (
          <Link key={link.href} href={link.href} className="hover:text-zinc-400">
            {link.label}
          </Link>
        ))}
      </nav>
    </footer>
  );
}

export function supportEmail(): string {
  return SUPPORT_EMAIL;
}
