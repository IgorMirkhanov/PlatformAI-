import type { CloudPaymentsPayOptions, CloudPaymentsWidgetCallbacks } from "@/types/cloudpayments";

const TIPTOP_WIDGET_SCRIPT = "https://widget.tiptop-pay.kz/bundles/cloudpayments.js";

let scriptPromise: Promise<void> | null = null;

export function resolveTipTopPublicId(fallback?: string | null): string {
  return (
    (process.env.NEXT_PUBLIC_TIPTOP_PUBLIC_ID || "").trim() ||
    (fallback || "").trim()
  );
}

export function loadTipTopWidgetScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("TipTop widget is browser-only."));
  }
  if (window.cp?.CloudPayments) {
    return Promise.resolve();
  }
  if (scriptPromise) {
    return scriptPromise;
  }

  scriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${TIPTOP_WIDGET_SCRIPT}"]`,
    );
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("Failed to load TipTop Pay widget script.")),
        { once: true },
      );
      if (window.cp?.CloudPayments) {
        resolve();
      }
      return;
    }

    const script = document.createElement("script");
    script.src = TIPTOP_WIDGET_SCRIPT;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error("Failed to load TipTop Pay widget script."));
    };
    document.head.appendChild(script);
  });

  return scriptPromise;
}

export async function openTipTopPayWidget(
  options: CloudPaymentsPayOptions,
  callbacks?: CloudPaymentsWidgetCallbacks,
): Promise<void> {
  await loadTipTopWidgetScript();
  const CloudPaymentsCtor = window.cp?.CloudPayments;
  if (!CloudPaymentsCtor) {
    throw new Error("TipTop Pay SDK (window.cp.CloudPayments) is not available.");
  }
  const widget = new CloudPaymentsCtor();
  widget.pay("charge", options, callbacks);
}
