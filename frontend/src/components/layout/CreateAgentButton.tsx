"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { CreateAgentModal } from "@/components/bots/CreateAgentModal";
import { canManageBots } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useBotStore } from "@/store/useBotStore";

interface CreateAgentButtonProps {
  variant?: "link" | "button" | "icon";
  className?: string;
  onNavigate?: () => void;
  onCreated?: () => void;
  label?: string;
}

export function CreateAgentButton({
  variant = "link",
  className,
  onNavigate,
  onCreated,
  label = "Создать агента",
}: CreateAgentButtonProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const role = useBotStore((state) => state.currentUser?.role);
  const allowed = canManageBots(role);

  if (!allowed) {
    return null;
  }

  const handleOpen = (): void => {
    onNavigate?.();
    setModalOpen(true);
  };

  const handleCreated = (): void => {
    onCreated?.();
    setModalOpen(false);
  };

  if (variant === "icon") {
    return (
      <>
        <button
          type="button"
          onClick={handleOpen}
          className={cn(
            "text-[10px] font-semibold text-violet-400 hover:text-violet-300",
            className,
          )}
          aria-label="Создать агента"
        >
          +
        </button>
        <CreateAgentModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onCreated={handleCreated}
        />
      </>
    );
  }

  if (variant === "button") {
    return (
      <>
        <button
          type="button"
          onClick={handleOpen}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500",
            className,
          )}
        >
          <Plus className="h-4 w-4" />
          {label}
        </button>
        <CreateAgentModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onCreated={handleCreated}
        />
      </>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className={cn(
          "inline-flex items-center gap-1.5 text-xs font-medium text-violet-400 hover:text-violet-300",
          className,
        )}
      >
        + {label}
      </button>
      <CreateAgentModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={handleCreated}
      />
    </>
  );
}
