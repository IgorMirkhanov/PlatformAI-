"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

/** Legacy agent channels tab → MoonAI Omnichannel Hub. */
export default function LegacyChannelsRedirectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/dashboard/channels-agent/${params.id}/telegram`);
  }, [params.id, router]);

  return null;
}
