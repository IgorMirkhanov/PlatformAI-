"use client";

import { VkontakteChannelForm } from "@/components/bots/channels/forms/VkontakteChannelForm";
import { ChannelModalShell } from "@/components/channels/ChannelModalShell";
import type { ChannelDefinition, ChannelStatus, SetupChannelRequest } from "@/types/channels";

interface VkontakteChannelModalProps {
  open: boolean;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function VkontakteChannelModal({
  open,
  definition,
  status,
  saving,
  onClose,
  onSubmit,
}: VkontakteChannelModalProps) {
  return (
    <ChannelModalShell
      open={open}
      definition={definition}
      status={status}
      saving={saving}
      onClose={onClose}
    >
      {status ? (
        <VkontakteChannelForm status={status} saving={saving} onSubmit={onSubmit} />
      ) : null}
    </ChannelModalShell>
  );
}
