"use client";

import { create } from "zustand";

export type ToastVariant = "success" | "error" | "info" | "prompting" | "knowledge" | "settings";

export interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastState {
  toasts: ToastItem[];
  showToast: (message: string, variant?: ToastVariant) => void;
  dismissToast: (id: string) => void;
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  showToast: (message, variant = "info") => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    set({ toasts: [...get().toasts, { id, message, variant }] });
    window.setTimeout(() => {
      get().dismissToast(id);
    }, 4000);
  },
  dismissToast: (id) =>
    set({ toasts: get().toasts.filter((toast) => toast.id !== id) }),
}));

export function useToast() {
  const showToast = useToastStore((state) => state.showToast);
  return { showToast };
}
