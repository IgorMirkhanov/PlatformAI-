"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { FileText, Loader2, UploadCloud, Wallet, X } from "lucide-react";

import { submitDepositRequest } from "@/lib/api";
import { formatBillingCurrency } from "@/lib/billing-utils";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { useBotStore } from "@/store/useBotStore";
import {
  ACCEPTED_RECEIPT_MIME_TYPES,
  DEFAULT_BILLING_CURRENCY,
  MANUAL_DEPOSIT_PAYMENT_DETAILS,
  TOP_UP_PRESETS_KZT,
} from "@/types/billing";

interface ManualDepositWidgetProps {
  open: boolean;
  onClose: () => void;
}

const ACCEPT_ATTR = ".png,.jpg,.jpeg,.pdf,image/png,image/jpeg,application/pdf";

function isAcceptedReceipt(file: File): boolean {
  const mime = file.type.toLowerCase();
  if ((ACCEPTED_RECEIPT_MIME_TYPES as readonly string[]).includes(mime)) {
    return true;
  }
  const name = file.name.toLowerCase();
  return name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".pdf");
}

function toPureIntegerAmount(raw: string | number): number {
  const parsed = typeof raw === "number" ? raw : Number(String(raw).replace(",", ".").trim());
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return NaN;
  }
  return Math.trunc(parsed);
}

export function ManualDepositWidget({ open, onClose }: ManualDepositWidgetProps) {
  const billing = useBotStore((state) => state.billing);
  const loadBillingTransactions = useBotStore((state) => state.loadBillingTransactions);
  const { showToast } = useToast();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [amount, setAmount] = useState(String(TOP_UP_PRESETS_KZT[1]));
  const [receipt, setReceipt] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [mounted, setMounted] = useState(false);

  const currency = billing?.currency ?? DEFAULT_BILLING_CURRENCY;
  const amountNumber = toPureIntegerAmount(amount);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    setAmount(String(TOP_UP_PRESETS_KZT[1]));
    setReceipt(null);
    setDragging(false);
    setSubmitting(false);
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

  const handleSubmit = async (): Promise<void> => {
    const finalAmount = toPureIntegerAmount(amount);
    if (!Number.isFinite(finalAmount) || finalAmount <= 0) {
      showToast("Введите сумму пополнения больше нуля.", "error");
      return;
    }
    if (!receipt) {
      showToast("Прикрепите чек об оплате.", "error");
      return;
    }

    setSubmitting(true);
    try {
      const result = await submitDepositRequest({ amount: finalAmount, receipt });
      void loadBillingTransactions();
      void useBotStore.getState().loadBilling();
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
      setSubmitting(false);
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
                  <Wallet className="h-4 w-4 text-zinc-300" />
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
                    Ручное пополнение
                  </p>
                </div>
                <h2 className="text-lg font-semibold text-zinc-50">Пополнить баланс</h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Текущий баланс: {formatBillingCurrency(billing?.balance ?? 0, currency)}
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
              <section className="rounded-2xl border border-zinc-800/90 bg-zinc-900/40 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                  {MANUAL_DEPOSIT_PAYMENT_DETAILS.title}
                </p>
                <div className="mt-3 space-y-3 text-sm text-zinc-300">
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-zinc-500">
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.kaspi.label}
                    </p>
                    <p className="mt-0.5 font-medium text-zinc-100">
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.kaspi.value}
                    </p>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.kaspi.hint}
                    </p>
                  </div>
                  <div className="h-px bg-zinc-800" />
                  <div className="space-y-1 text-xs leading-relaxed text-zinc-400">
                    <p>
                      <span className="text-zinc-500">Получатель:</span>{" "}
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.bank.beneficiary}
                    </p>
                    <p>
                      <span className="text-zinc-500">БИН:</span>{" "}
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.bank.bin}
                    </p>
                    <p>
                      <span className="text-zinc-500">ИИК:</span>{" "}
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.bank.iik}
                    </p>
                    <p>
                      <span className="text-zinc-500">БИК:</span>{" "}
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.bank.bik}
                    </p>
                    <p>
                      <span className="text-zinc-500">Банк:</span>{" "}
                      {MANUAL_DEPOSIT_PAYMENT_DETAILS.bank.bankName}
                    </p>
                  </div>
                </div>
              </section>

              <section>
                <label className="text-xs text-zinc-500">Сумма пополнения (₸)</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {TOP_UP_PRESETS_KZT.map((value) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => {
                        setAmount(String(Math.trunc(value)));
                      }}
                      className={cn(
                        "rounded-xl border px-3 py-2 text-sm font-medium transition",
                        amountNumber === value
                          ? "border-zinc-500 bg-zinc-800 text-zinc-100"
                          : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:bg-zinc-900/70",
                      )}
                    >
                      {formatBillingCurrency(value, currency)}
                    </button>
                  ))}
                </div>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={amount}
                  onChange={(event) => {
                    const next = event.target.value;
                    if (next === "") {
                      setAmount("");
                      return;
                    }
                    const integer = toPureIntegerAmount(next);
                    setAmount(Number.isFinite(integer) ? String(integer) : next.replace(/[^\d]/g, ""));
                  }}
                  placeholder="Введите сумму"
                  className="mt-3 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
                />
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
                    "mt-2 flex w-full flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-8 text-center transition",
                    dragging
                      ? "border-zinc-400 bg-zinc-900/80"
                      : "border-zinc-700 bg-zinc-950/50 hover:border-zinc-500 hover:bg-zinc-900/60",
                  )}
                >
                  <UploadCloud className="h-6 w-6 text-zinc-400" />
                  <p className="text-sm text-zinc-300">Перетащите файл сюда или нажмите для выбора</p>
                  <p className="text-[11px] text-zinc-600">PNG, JPG или PDF · до 50 МБ</p>
                </button>

                {receipt ? (
                  <div className="mt-3 flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/50 px-3 py-2.5">
                    <FileText className="h-4 w-4 shrink-0 text-zinc-400" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-zinc-200">{receipt.name}</p>
                      <p className="text-[10px] text-zinc-500">
                        {(receipt.size / 1024).toFixed(1)} КБ
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setReceipt(null)}
                      className="rounded-md p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : null}
              </section>
            </div>

            <div className="border-t border-zinc-800/80 p-5">
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={submitting}
                className={cn(
                  "inline-flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition",
                  "bg-gradient-to-r from-violet-600 to-fuchsia-600 shadow-glow-purple",
                  "hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-50",
                )}
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Отправить подтверждение
              </button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}
