"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LegacyAdminBillingRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/billing");
  }, [router]);
  return null;
}
