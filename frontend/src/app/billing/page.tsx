"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Canonical billing UI lives at /dashboard/billing. */
export default function BillingAliasRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard/billing");
  }, [router]);
  return null;
}
