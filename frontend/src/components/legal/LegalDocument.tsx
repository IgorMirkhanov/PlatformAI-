import type { ReactNode } from "react";
import Link from "next/link";

import { SiteFooter } from "@/components/legal/SiteFooter";

export function LegalDocument({
  title,
  updated,
  children,
}: {
  title: string;
  updated?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#050507] text-zinc-200">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <Link
          href="/"
          className="text-xs text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
        >
          ← MP.AI
        </Link>
        <article>
          <h1 className="mt-6 text-3xl font-semibold tracking-tight text-zinc-50">{title}</h1>
          {updated ? <p className="mt-2 text-xs text-zinc-500">{updated}</p> : null}
          <div className="prose prose-invert mt-8 max-w-none space-y-4 text-sm leading-6 text-zinc-400">
            {children}
          </div>
        </article>
      </div>
      <SiteFooter />
    </div>
  );
}
