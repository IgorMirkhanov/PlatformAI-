"use client";

import { TelegramChannelForm } from "@/components/bots/channels/forms/TelegramChannelForm";
import { ChannelModalShell } from "@/components/channels/ChannelModalShell";
import type { ChannelDefinition, ChannelStatus, SetupChannelRequest } from "@/types/channels";

interface TelegramChannelModalProps {
  open: boolean;
  botId: string;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function TelegramChannelModal({
  open,
  botId,
  definition,
  status,
  saving,
  onClose,
  onSubmit,
}: TelegramChannelModalProps) {
  return (
    <ChannelModalShell
      open={open}
      definition={definition}
      status={status}
      saving={saving}
      onClose={onClose}
    >
      {status ? (
        <TelegramChannelForm botId={botId} status={status} saving={saving} onSubmit={onSubmit} />
      ) : null}
    </ChannelModalShell>
  );
}
