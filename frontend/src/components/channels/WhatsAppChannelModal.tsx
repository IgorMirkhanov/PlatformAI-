"use client";

import { WhatsAppChannelForm } from "@/components/bots/channels/forms/WhatsAppChannelForm";
import { ChannelModalShell } from "@/components/channels/ChannelModalShell";
import type { ChannelDefinition, ChannelStatus, SetupChannelRequest } from "@/types/channels";

interface WhatsAppChannelModalProps {
  open: boolean;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function WhatsAppChannelModal({
  open,
  definition,
  status,
  saving,
  onClose,
  onSubmit,
}: WhatsAppChannelModalProps) {
  return (
    <ChannelModalShell
      open={open}
      definition={definition}
      status={status}
      saving={saving}
      onClose={onClose}
    >
      {status ? (
        <WhatsAppChannelForm status={status} saving={saving} onSubmit={onSubmit} />
      ) : null}
    </ChannelModalShell>
  );
}
