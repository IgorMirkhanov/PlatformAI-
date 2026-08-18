"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";

/** Legacy layout — all /dashboard/admin/* routes redirect into /admin. */
export default function LegacyAdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin");
  }, [router]);
  return <>{children}</>;
}
