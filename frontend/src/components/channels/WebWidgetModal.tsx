"use client";

import { WebWidgetChannelForm } from "@/components/bots/channels/forms/WebWidgetChannelForm";
import { ChannelModalShell } from "@/components/channels/ChannelModalShell";
import type { ChannelDefinition, ChannelStatus, SetupChannelRequest } from "@/types/channels";

interface WebWidgetModalProps {
  open: boolean;
  botId: string;
  definition: ChannelDefinition | null;
  status: ChannelStatus | null;
  saving: boolean;
  onClose: () => void;
  onSubmit: (payload: SetupChannelRequest) => Promise<void>;
}

export function WebWidgetModal({
  open,
  botId,
  definition,
  status,
  saving,
  onClose,
  onSubmit,
}: WebWidgetModalProps) {
  return (
    <ChannelModalShell
      open={open}
      definition={definition}
      status={status}
      saving={saving}
      onClose={onClose}
    >
      {status ? (
        <WebWidgetChannelForm botId={botId} status={status} saving={saving} onSubmit={onSubmit} />
      ) : null}
    </ChannelModalShell>
  );
}
