"use client";

import { Suspense } from "react";

import BillingPageClient from "./BillingPageClient";

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center text-sm text-zinc-500">
          Loading billing…
        </div>
      }
    >
      <BillingPageClient />
    </Suspense>
  );
}
