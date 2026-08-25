import {
  HUB_OAUTH_MESSAGE_TYPE,
  type HubOAuthMessage,
} from "@/types/integration-hub";

function readPopupRedirectResult(popup: Window): HubOAuthMessage | null {
  try {
    if (popup.closed || popup.location.origin !== window.location.origin) return null;
    const url = new URL(popup.location.href);
    if (!url.pathname.includes("/integrations/hub/oauth-result")) return null;
    return {
      type: HUB_OAUTH_MESSAGE_TYPE,
      provider: url.searchParams.get("provider") || "",
      status: url.searchParams.get("status") || "error",
      connectionId: url.searchParams.get("connection_id"),
      message: url.searchParams.get("message"),
    };
  } catch {
    return null;
  }
}

export function isHubOAuthMessage(data: unknown): data is HubOAuthMessage {
  if (!data || typeof data !== "object") return false;
  const row = data as Record<string, unknown>;
  return row.type === HUB_OAUTH_MESSAGE_TYPE && typeof row.provider === "string";
}

export function openHubOAuthPopup(authorizeUrl: string): Promise<HubOAuthMessage> {
  return new Promise((resolve, reject) => {
    const width = 620;
    const height = 740;
    const left = Math.max(0, window.screenX + (window.outerWidth - width) / 2);
    const top = Math.max(0, window.screenY + (window.outerHeight - height) / 2);
    // Do not set noopener: the result page needs window.opener to postMessage.
    const popup = window.open(
      authorizeUrl,
      "mpai-hub-oauth",
      `popup=yes,width=${width},height=${height},left=${left},top=${top}`,
    );
    if (!popup) {
      reject(new Error("Браузер заблокировал окно авторизации. Разрешите всплывающие окна."));
      return;
    }

    let settled = false;
    const finish = (result: HubOAuthMessage | Error) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      window.clearInterval(timer);
      window.clearTimeout(timeout);
      try {
        popup.close();
      } catch {
        /* ignore */
      }
      if (result instanceof Error) reject(result);
      else resolve(result);
    };

    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (!isHubOAuthMessage(event.data)) return;
      finish(event.data);
    };

    window.addEventListener("message", onMessage);
    const timer = window.setInterval(() => {
      const redirected = readPopupRedirectResult(popup);
      if (redirected) {
        finish(redirected);
        return;
      }
      if (popup.closed && !settled) {
        finish({
          type: HUB_OAUTH_MESSAGE_TYPE,
          provider: "",
          status: "cancelled",
          message: "Окно авторизации закрыто.",
        });
      }
    }, 400);
    const timeout = window.setTimeout(() => {
      finish(new Error("Истекло время ожидания OAuth. Попробуйте ещё раз."));
    }, 10 * 60 * 1000);
  });
}
