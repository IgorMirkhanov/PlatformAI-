"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2, Shield } from "lucide-react";

import { AdminSidebar } from "@/components/admin/AdminSidebar";
import { canAccessAdminPanel } from "@/lib/auth/admin";
import { useBotStore } from "@/store/useBotStore";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isLoginRoute = pathname === "/admin/login";
  const isForbiddenRoute = pathname === "/admin/forbidden";
  const isGateExempt = isLoginRoute || isForbiddenRoute;
  const currentUser = useBotStore((state) => state.currentUser);
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const currentUserLoading = useBotStore((state) => state.currentUserLoading);

  useEffect(() => {
    void loadCurrentUser();
  }, [loadCurrentUser]);

  useEffect(() => {
    if (isGateExempt) return;
    if (currentUserLoading) return;
    if (!currentUser) {
      router.replace(`/admin/login?from=${encodeURIComponent(pathname || "/admin")}`);
      return;
    }
    if (!canAccessAdminPanel()) {
      router.replace("/admin/forbidden");
    }
  }, [currentUser, currentUserLoading, isGateExempt, pathname, router]);

  if (isGateExempt) {
    return <>{children}</>;
  }

  if (currentUserLoading || !currentUser) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-zinc-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Проверка доступа…
      </div>
    );
  }

  if (!canAccessAdminPanel()) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-4 text-center">
        <Shield className="h-10 w-10 text-zinc-600" />
        <p className="text-sm text-zinc-500">403 Forbidden — нет прав доступа к админ-панели.</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-full bg-gradient-to-br from-zinc-950 via-[#0a0a0c] to-zinc-950">
      <div className="sticky top-0 hidden h-screen lg:block">
        <AdminSidebar />
      </div>
      <div className="min-w-0 flex-1">
        <div className="border-b border-zinc-800/80 bg-zinc-950/70 px-4 py-3 lg:hidden">
          <AdminSidebar />
        </div>
        <div className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-8 lg:py-8">{children}</div>
      </div>
    </div>
  );
}
