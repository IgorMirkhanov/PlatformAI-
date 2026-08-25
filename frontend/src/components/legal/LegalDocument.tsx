import type { ReactNode } from "react";
import Link from "next/link";

import { SiteFooter } from "@/components/legal/SiteFooter";

export function LegalDocument({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#050507] text-zinc-200">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <Link href="/" className="text-xs text-zinc-500 hover:text-zinc-300">
          ← MP.AI
        </Link>
        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-zinc-50">{title}</h1>
        <div className="prose prose-invert mt-8 max-w-none space-y-4 text-sm leading-6 text-zinc-400">
          {children}
        </div>
      </div>
      <SiteFooter />
    </div>
  );
}
