"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Legacy path — redirects to the full Admin Panel at /admin. */
export default function LegacyAdminRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin");
  }, [router]);
  return null;
}
