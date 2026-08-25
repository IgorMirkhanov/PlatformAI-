"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { Loader2 } from "lucide-react";

import { HUB_OAUTH_MESSAGE_TYPE } from "@/types/integration-hub";

function OAuthResultInner() {
  const params = useSearchParams();
  const provider = params.get("provider") || "";
  const status = params.get("status") || "error";
  const connectionId = params.get("connection_id");
  const message = params.get("message");

  useEffect(() => {
    const payload = {
      type: HUB_OAUTH_MESSAGE_TYPE,
      provider,
      status,
      connectionId,
      message,
    };
    if (window.opener && !window.opener.closed) {
      window.opener.postMessage(payload, window.location.origin);
      window.setTimeout(() => window.close(), 250);
      return;
    }
    window.setTimeout(() => {
      window.location.replace("/dashboard/integrations");
    }, 800);
  }, [connectionId, message, provider, status]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-sm text-zinc-400">
      <Loader2 className="h-5 w-5 animate-spin text-violet-400" />
      {status === "connected" ? "Интеграция подключена. Можно закрыть окно." : "Завершение авторизации…"}
    </div>
  );
}

export default function HubOAuthResultPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center text-zinc-500">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      }
    >
      <OAuthResultInner />
    </Suspense>
  );
}
