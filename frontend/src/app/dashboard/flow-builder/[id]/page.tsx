"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

/** Canonical bot constructor lives at `/flow-builder?botId=…`. */
export default function LegacyBotFlowBuilderRedirect() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const botId = params?.id;

  useEffect(() => {
    if (!botId) {
      router.replace("/dashboard/flows");
      return;
    }
    router.replace(`/flow-builder?botId=${encodeURIComponent(botId)}`);
  }, [botId, router]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-zinc-500">
      Переход в конструктор…
    </div>
  );
}
