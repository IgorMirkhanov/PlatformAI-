"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronDown,
  CreditCard,
  FileText,
  Globe,
  Loader2,
  Sparkles,
  UploadCloud,
  Wallet,
  X,
} from "lucide-react";

import { submitDepositRequest, topUpByCard } from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useBotStore } from "@/store/useBotStore";
import {
  ACCEPTED_RECEIPT_MIME_TYPES,
  DEFAULT_BILLING_CURRENCY,
  MANUAL_DEPOSIT_PAYMENT_DETAILS,
  TOP_UP_PRESETS_KZT,
  TOP_UP_PRESETS_USD,
  type BillingCurrency,
} from "@/types/billing";

interface BalanceTopUpModalProps {
  open: boolean;
  onClose: () => void;
}

/** @deprecated Use BalanceTopUpModal */
export type ManualDepositWidgetProps = BalanceTopUpModalProps;

type PayProvider = "stripe" | "tiptop";

const ACCEPT_ATTR = ".png,.jpg,.jpeg,.pdf,image/png,image/jpeg,application/pdf";

function isAcceptedReceipt(file: File): boolean {
  const mime = file.type.toLowerCase();
  if ((ACCEPTED_RECEIPT_MIME_TYPES as readonly string[]).includes(mime)) {
    return true;
  }
  const name = file.name.toLowerCase();
  return name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".pdf");
}

function parseAmount(raw: string, currency: BillingCurrency): number {
  const parsed = Number(String(raw).replace(",", ".").trim());
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return NaN;
  }
  return currency === "KZT" ? Math.trunc(parsed) : Math.round(parsed * 100) / 100;
}

function AmountSection({
  amount,
  amountNumber,
  currency,
  inputRef,
  onSelect,
  onChange,
}: {
  amount: string;
  amountNumber: number;
  currency: BillingCurrency;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onSelect: (value: number) => void;
  onChange: (value: string) => void;
}) {
  const presets = currency === "USD" ? TOP_UP_PRESETS_USD : TOP_UP_PRESETS_KZT;

  return (
    <section>
      <label htmlFor="topup-amount" className="text-xs text-zinc-500">
        Введите сумму пополнения
      </label>
      <div className="mt-2 flex flex-wrap gap-2">
        {presets.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => onSelect(value)}
            className={cn(
              "rounded-xl border px-3 py-2 text-sm font-medium transition",
              amountNumber === value
                ? "border-violet-500/60 bg-violet-500/10 text-violet-100"
                : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:bg-zinc-900/70",
            )}
          >
            {formatBillingCurrency(value, currency)}
          </button>
        ))}
      </div>
      <input
        ref={inputRef}
        id="topup-amount"
        type="number"
        min={currency === "USD" ? "0.5" : "100"}
        step={currency === "USD" ? "0.01" : "1"}
        value={amount}
        onChange={(event) => onChange(event.target.value)}
        placeholder={currency === "USD" ? "Сумма в USD" : "Сумма в ₸"}
        className="mt-3 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
      />
    </section>
  );
}

export function BalanceTopUpModal({ open, onClose }: BalanceTopUpModalProps) {
  const billing = useBotStore((state) => state.billing);
  const loadBillingTransactions = useBotStore((state) => state.loadBillingTransactions);
  const { showToast } = useToast();

  const amountInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [currency, setCurrency] = useState<BillingCurrency>("KZT");
  const [amount, setAmount] = useState(String(TOP_UP_PRESETS_KZT[1]));
  const [manualOpen, setManualOpen] = useState(false);
  const [receipt, setReceipt] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState<PayProvider | "saved" | "manual" | null>(null);
  const [mounted, setMounted] = useState(false);

  const displayCurrency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const amountNumber = parseAmount(amount, currency);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    setCurrency("KZT");
    setAmount(String(TOP_UP_PRESETS_KZT[1]));
    setManualOpen(false);
    setReceipt(null);
    setDragging(false);
    setSubmitting(null);
    window.setTimeout(() => amountInputRef.current?.focus(), 120);
  }, [open]);

  const assignReceipt = useCallback(
    (file: File | null): void => {
      if (!file) {
        setReceipt(null);
        return;
      }
      if (!isAcceptedReceipt(file)) {
        showToast("Загрузите чек в формате PNG, JPG или PDF.", "error");
        return;
      }
      setReceipt(file);
    },
    [showToast],
  );

  const refreshBilling = (): void => {
    void loadBillingTransactions();
    void useBotStore.getState().loadBilling();
  };

  const handlePay = async (
    provider: PayProvider,
    options?: { useSavedCard?: boolean; payCurrency?: BillingCurrency },
  ): Promise<void> => {
    const payCurrency: BillingCurrency =
      options?.payCurrency ??
      (provider === "stripe" && !options?.useSavedCard ? "USD" : currency);
    const finalAmount = parseAmount(amount, payCurrency);
    if (!Number.isFinite(finalAmount) || finalAmount <= 0) {
      showToast("Введите сумму пополнения больше нуля.", "error");
      return;
    }

    setSubmitting(options?.useSavedCard ? "saved" : provider);
    try {
      const result = await topUpByCard({
        amount: finalAmount,
        currency: payCurrency,
        provider,
        use_saved_card: Boolean(options?.useSavedCard),
      });

      const redirectUrl = result.checkout_url || result.payment_url;
      if (result.status === "redirect" && redirectUrl) {
        window.location.assign(redirectUrl);
        return;
      }

      if (result.status === "processing") {
        showToast(
          result.message ||
            "Платеж отправлен. Баланс обновится после подтверждения эквайера.",
          "success",
        );
        onClose();
        return;
      }

      showToast(result.message || "Не удалось инициализировать оплату.", "error");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Не удалось выполнить оплату.";
      showToast(message, "error");
    } finally {
      setSubmitting(null);
    }
  };

  const handleManualSubmit = async (): Promise<void> => {
    const finalAmount = parseAmount(amount, "KZT");
    if (!Number.isFinite(finalAmount) || finalAmount <= 0) {
      showToast("Введите сумму пополнения больше нуля.", "error");
      return;
    }
    if (!receipt) {
      showToast("Прикрепите чек об оплате.", "error");
      return;
    }

    setSubmitting("manual");
    try {
      const result = await submitDepositRequest({ amount: finalAmount, receipt });
      refreshBilling();
      showToast(
        result.message ||
          "Заявка принята! Баланс обновится после проверки чека оператором.",
        "success",
      );
      onClose();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Не удалось отправить заявку на пополнение.";
      showToast(message, "error");
    } finally {
      setSubmitting(null);
    }
  };

  if (!mounted) {
    return null;
  }

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0"
            onClick={onClose}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
            className={cn(
              "relative z-10 m-auto flex w-full max-w-md max-h-[90vh] flex-col overflow-y-auto rounded-2xl",
              "border border-zinc-800/90 bg-zinc-950/90 shadow-2xl backdrop-blur-2xl",
            )}
          >
            <div className="flex items-start justify-between gap-3 border-b border-zinc-800/80 px-5 py-4">
              <div>
                <div className="mb-1.5 flex items-center gap-2">
                  <Wallet className="h-4 w-4 text-violet-300" />
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
                    Billing
                  </p>
                </div>
                <h2 className="text-lg font-semibold text-zinc-50">Пополнить баланс</h2>
                <p className="mt-1.5 text-xs italic text-zinc-500">
                  Пополните баланс, чтобы обеспечить стабильную работу агента и доступ ко всем
                  функциям
                </p>
                <p className="mt-2 text-xs text-zinc-600">
                  Текущий баланс: {formatBillingCurrency(billing?.balance ?? 0, displayCurrency)}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
              <AmountSection
                amount={amount}
                amountNumber={amountNumber}
                currency={currency}
                inputRef={amountInputRef}
                onSelect={(value) => {
                  setCurrency(currency === "USD" ? "USD" : "KZT");
                  setAmount(String(value));
                }}
                onChange={setAmount}
              />

              <div className="space-y-2.5">
                <button
                  type="button"
                  disabled={submitting !== null}
                  onClick={() => void handlePay("stripe", { useSavedCard: true, payCurrency: "KZT" })}
                  className={cn(
                    "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition",
                    "bg-gradient-to-r from-violet-600 to-fuchsia-600 shadow-glow-purple",
                    "hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50",
                  )}
                >
                  {submitting === "saved" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  Tip! Пополнить с привязанной карты
                </button>

                <button
                  type="button"
                  disabled={submitting !== null}
                  onClick={() => {
                    setCurrency("KZT");
                    void handlePay("tiptop", { payCurrency: "KZT" });
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-left transition",
                    "hover:border-zinc-600 hover:bg-zinc-900 disabled:opacity-50",
                  )}
                >
                  <div className="flex items-center gap-3">
                    <CreditCard className="h-4 w-4 shrink-0 text-zinc-300" />
                    <div>
                      <p className="text-sm font-medium text-zinc-100">Пополнить через TipTop Pay</p>
                      <p className="text-[11px] text-zinc-500">Оплата картой в тенге</p>
                    </div>
                  </div>
                  <span className="shrink-0 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                    Казахстан / KZT
                  </span>
                  {submitting === "tiptop" ? <Loader2 className="h-4 w-4 animate-spin text-zinc-400" /> : null}
                </button>

                <button
                  type="button"
                  disabled={submitting !== null}
                  onClick={() => {
                    setCurrency("USD");
                    setAmount(String(TOP_UP_PRESETS_USD[0]));
                    void handlePay("stripe", { payCurrency: "USD" });
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-left transition",
                    "hover:border-zinc-600 hover:bg-zinc-900 disabled:opacity-50",
                  )}
                >
                  <div className="flex items-center gap-3">
                    <Globe className="h-4 w-4 shrink-0 text-zinc-300" />
                    <div>
                      <p className="text-sm font-medium text-zinc-100">Пополнить через Stripe</p>
                      <p className="text-[11px] text-zinc-500">Международные карты</p>
                    </div>
                  </div>
                  <span className="shrink-0 rounded-md bg-blue-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-300">
                    Международные / USD
                  </span>
                  {submitting === "stripe" ? <Loader2 className="h-4 w-4 animate-spin text-zinc-400" /> : null}
                </button>
              </div>

              <button
                type="button"
                onClick={() => setManualOpen((value) => !value)}
                className="flex w-full items-center justify-between rounded-lg px-1 py-1 text-xs text-zinc-500 transition hover:text-zinc-300"
              >
                <span>Безналичный перевод / Kaspi (ручная проверка)</span>
                <ChevronDown
                  className={cn("h-4 w-4 transition", manualOpen ? "rotate-180" : "")}
                />
              </button>

              {manualOpen ? (
                <div className="space-y-4 rounded-2xl border border-zinc-800/90 bg-zinc-900/30 p-4">
                  <section className="rounded-xl border border-zinc-800/90 bg-zinc-900/40 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.title}
                    </p>
                    <div className="mt-2 space-y-2 text-xs text-zinc-400">
                      <p>{MANUAL_DEPOSIT_PAYMENT_DETAILS.kaspi.value}</p>
                      <p>{MANUAL_DEPOSIT_PAYMENT_DETAILS.bank.beneficiary}</p>
                    </div>
                  </section>

                  <section>
                    <label className="text-xs text-zinc-500">Загрузить чек об оплате</label>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept={ACCEPT_ATTR}
                      className="hidden"
                      onChange={(event) => assignReceipt(event.target.files?.[0] ?? null)}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      onDragEnter={(event) => {
                        event.preventDefault();
                        setDragging(true);
                      }}
                      onDragOver={(event) => {
                        event.preventDefault();
                        setDragging(true);
                      }}
                      onDragLeave={(event) => {
                        event.preventDefault();
                        setDragging(false);
                      }}
                      onDrop={(event) => {
                        event.preventDefault();
                        setDragging(false);
                        assignReceipt(event.dataTransfer.files?.[0] ?? null);
                      }}
                      className={cn(
                        "mt-2 flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center transition",
                        dragging
                          ? "border-zinc-400 bg-zinc-900/80"
                          : "border-zinc-700 bg-zinc-950/50 hover:border-zinc-500",
                      )}
                    >
                      <UploadCloud className="h-5 w-5 text-zinc-400" />
                      <p className="text-xs text-zinc-400">PNG, JPG или PDF</p>
                    </button>
                    {receipt ? (
                      <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-800 px-3 py-2">
                        <FileText className="h-4 w-4 text-zinc-400" />
                        <span className="truncate text-xs text-zinc-300">{receipt.name}</span>
                      </div>
                    ) : null}
                  </section>

                  <button
                    type="button"
                    onClick={() => void handleManualSubmit()}
                    disabled={submitting !== null}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 px-4 py-2.5 text-sm font-medium text-zinc-200 transition hover:bg-zinc-800 disabled:opacity-50"
                  >
                    {submitting === "manual" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Отправить на проверку
                  </button>
                </div>
              ) : null}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

/** Backward-compatible export */
export const ManualDepositWidget = BalanceTopUpModal;
