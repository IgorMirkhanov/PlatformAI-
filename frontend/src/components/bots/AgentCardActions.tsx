"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Copy, MoreVertical, Trash2 } from "lucide-react";

import { DeleteBotModal } from "@/components/modals/DeleteBotModal";
import { Button } from "@/components/ui/button";
import { cloneBot, deleteBot } from "@/lib/api";
import { useAsyncAction } from "@/lib/hooks/use-async-action";
import { canManageBots } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";

interface AgentCardActionsProps {
  botId: string;
  botName: string;
  onRefresh?: () => void;
  className?: string;
}

export function AgentCardActions({
  botId,
  botName,
  onRefresh,
  className,
}: AgentCardActionsProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const role = useBotStore((state) => state.currentUser?.role);
  const activeBotId = useBotStore((state) => state.activeBotId);
  const setActiveBotId = useBotStore((state) => state.setActiveBotId);
  const allowed = canManageBots(role);

  useEffect(() => {
    if (!menuOpen) return;
    const handlePointer = (event: MouseEvent): void => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointer);
    return () => document.removeEventListener("mousedown", handlePointer);
  }, [menuOpen]);

  const cloneAction = useCallback(async () => {
    const result = await cloneBot(botId);
    onRefresh?.();
    return result;
  }, [botId, onRefresh]);

  const { run: runClone, isLoading: cloning } = useAsyncAction(cloneAction, {
    successMessage: "Бот склонирован.",
    errorMessage: "Не удалось клонировать бота.",
  });

  const deleteAction = useCallback(async () => {
    const result = await deleteBot(botId);
    setDeleteOpen(false);

    useBotStore.setState((state) => {
      const { [botId]: _removed, ...restProfiles } = state.agentProfiles;
      return {
        agentProfiles: restProfiles,
        activeBotId: state.activeBotId === botId ? null : state.activeBotId,
      };
    });
    if (activeBotId === botId) {
      setActiveBotId(null);
    }
    if (pathname?.includes(`/bots/${botId}`)) {
      router.replace("/dashboard");
    }

    onRefresh?.();
    return result;
  }, [activeBotId, botId, onRefresh, pathname, router, setActiveBotId]);

  const { run: runDelete, isLoading: deleting } = useAsyncAction(deleteAction, {
    successMessage: "Бот удалён.",
    errorMessage: "Не удалось удалить бота.",
  });

  if (!allowed) {
    return null;
  }

  return (
    <>
      <div ref={menuRef} className={cn("relative", className)}>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-9 w-9 text-zinc-400 hover:text-zinc-100"
          aria-label="Действия с ботом"
          aria-expanded={menuOpen}
          onClick={(event) => {
            event.stopPropagation();
            setMenuOpen((open) => !open);
          }}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>

        {menuOpen ? (
          <div className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-xl border border-zinc-800 bg-[#161618] py-1 shadow-xl">
            <button
              type="button"
              disabled={cloning}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-zinc-200 transition hover:bg-zinc-800 disabled:opacity-50"
              onClick={() => {
                setMenuOpen(false);
                void runClone();
              }}
            >
              <Copy className="h-3.5 w-3.5 text-zinc-400" />
              Клонировать
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-300 transition hover:bg-red-500/10"
              onClick={() => {
                setMenuOpen(false);
                setDeleteOpen(true);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Удалить
            </button>
          </div>
        ) : null}
      </div>

      <DeleteBotModal
        open={deleteOpen}
        botName={botName}
        isLoading={deleting}
        onClose={() => {
          if (!deleting) setDeleteOpen(false);
        }}
        onConfirm={() => {
          void runDelete();
        }}
      />
    </>
  );
}
