"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useParams } from "next/navigation";

export default function ChannelsAgentIndexPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/dashboard/channels-agent/${params.id}/telegram`);
  }, [params.id, router]);

  return null;
}
