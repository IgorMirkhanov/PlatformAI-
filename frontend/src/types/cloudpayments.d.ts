/** TipTop Pay / CloudPayments KZ widget (https://widget.tiptop-pay.kz) */
declare global {
  interface Window {
    cp?: {
      CloudPayments: new () => CloudPaymentsWidget;
    };
  }
}

export interface CloudPaymentsPayOptions {
  publicId: string;
  description: string;
  amount: number;
  currency: string;
  accountId?: string;
  invoiceId?: string;
  email?: string;
  skin?: string;
  data?: Record<string, unknown>;
  token?: string;
  /** Request TipTop / CloudPayments to tokenize card for one-click rebill */
  saveCard?: boolean;
  auth?: boolean;
}

export interface CloudPaymentsWidgetCallbacks {
  onSuccess?: (options: Record<string, unknown>) => void;
  onFail?: (reason: string, options: Record<string, unknown>) => void;
  onComplete?: (paymentResult: Record<string, unknown>, options: Record<string, unknown>) => void;
}

export interface CloudPaymentsWidget {
  pay: (
    type: "charge" | "auth",
    options: CloudPaymentsPayOptions,
    callbacks?: CloudPaymentsWidgetCallbacks,
  ) => void;
}

export {};
