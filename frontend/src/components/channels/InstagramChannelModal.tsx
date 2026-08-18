"use client";

import { InstagramChannelForm } from "@/components/bots/channels/forms/InstagramChannelForm";
import { ChannelModalShell } from "@/components/channels/ChannelModalShell";
import type { ChannelDefinition, ChannelStatus, SetupChannelRequest } from "@/types/channels";

interface InstagramChannelModalProps {
  open: boolean;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function InstagramChannelModal({
  open,
  definition,
  status,
  saving,
  onClose,
  onSubmit,
}: InstagramChannelModalProps) {
  return (
    <ChannelModalShell
      open={open}
      definition={definition}
      status={status}
      saving={saving}
      onClose={onClose}
    >
      {status ? (
        <InstagramChannelForm status={status} saving={saving} onSubmit={onSubmit} />
      ) : null}
    </ChannelModalShell>
  );
}
