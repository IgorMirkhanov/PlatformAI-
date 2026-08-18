"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Legacy path → Stage 4 dashboard team settings. */
export default function LegacyTeamSettingsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard/settings/team");
  }, [router]);
  return null;
}
