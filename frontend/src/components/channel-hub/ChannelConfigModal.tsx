"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, QrCode, X } from "lucide-react";

import { WhatsAppQrModal } from "@/components/channel-hub/WhatsAppQrModal";
import { useToast } from "@/hooks/useToast";
import {
  connectHubChannel,
  disconnectHubChannel,
  patchHubChannelEnabled,
} from "@/lib/api";
import {
  validateHubGreenApiForm,
  validateHubTelegramToken,
  validateHubWabaForm,
  validateHubWazzupForm,
} from "@/lib/channel-validation";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/store/useBotStore";
import {
  isHubChannelConnected,
  type ChannelConnectRequest,
  type HubChannelNavItem,
  type HubChannelStatusItem,
  type HubChannelType,
} from "@/types/channel-hub";

interface ChannelConfigModalProps {
  open: boolean;
  botId: string;
  channel: HubChannelNavItem | null;
  status: HubChannelStatusItem | null;
  onClose: () => void;
  onSaved: () => void;
}

function Field({
  label,
  value,
  onChange,
  password,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  password?: boolean;
  placeholder?: string;
}) {
  return (
    <label className="block text-xs font-medium text-zinc-400">
      {label}
      <input
        type={password ? "password" : "text"}
        value={value}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 w-full rounded-xl border border-zinc-800 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30"
      />
    </label>
  );
}

function buildConnectPayload(
  channelType: HubChannelType,
  fields: {
    token: string;
    apiId: string;
    apiHash: string;
    phone: string;
    apiKey: string;
    referenceId: string;
    instanceId: string;
    phoneNumberId: string;
    businessAccountId: string;
    accessToken: string;
    verifyToken: string;
    sipServer: string;
    sipLogin: string;
    sipPassword: string;
    sipPort: string;
  },
): ChannelConnectRequest {
  if (channelType === "telegram") {
    const validationError = validateHubTelegramToken(fields.token);
    if (validationError) throw new Error(validationError);
    return { token: fields.token.trim() };
  }

  if (channelType === "telegram_business") {
    if (!fields.apiId.trim() || !fields.apiHash.trim() || !fields.phone.trim()) {
      throw new Error("Укажите API ID, API Hash и номер телефона.");
    }
    return {
      token: fields.token.trim() || undefined,
      meta_data: {
        api_id: fields.apiId.trim(),
        api_hash: fields.apiHash.trim(),
        phone: fields.phone.trim(),
        provider: "telethon",
      },
    };
  }

  if (channelType === "wazzup") {
    const validationError = validateHubWazzupForm({
      api_key: fields.apiKey,
      channel_id: fields.referenceId,
    });
    if (validationError) throw new Error(validationError);
    return {
      api_key: fields.apiKey.trim(),
      reference_id: fields.referenceId.trim(),
    };
  }

  if (channelType === "whatsapp_qr" || channelType === "instagram") {
    const validationError = validateHubGreenApiForm({
      instance_id: fields.instanceId,
      api_token: fields.apiKey,
    });
    if (validationError) throw new Error(validationError);
    return {
      reference_id: fields.instanceId.trim(),
      api_key: fields.apiKey.trim(),
      access_token: fields.apiKey.trim(),
      token: fields.apiKey.trim(),
    };
  }

  if (channelType === "waba") {
    const validationError = validateHubWabaForm({
      phone_number_id: fields.phoneNumberId,
      business_account_id: fields.businessAccountId,
      access_token: fields.accessToken,
      verify_token: fields.verifyToken,
    });
    if (validationError) throw new Error(validationError);
    return {
      phone_number_id: fields.phoneNumberId.trim(),
      business_account_id: fields.businessAccountId.trim() || undefined,
      access_token: fields.accessToken.trim(),
      verify_token: fields.verifyToken.trim() || undefined,
    };
  }

  if (channelType === "calls") {
    if (!fields.sipServer.trim() || !fields.sipLogin.trim()) {
      throw new Error("Укажите SIP Server и Login.");
    }
    return {
      token: fields.sipPassword.trim() || undefined,
      reference_id: fields.sipLogin.trim(),
      meta_data: {
        sip_server: fields.sipServer.trim(),
        sip_login: fields.sipLogin.trim(),
        sip_password: fields.sipPassword.trim(),
        sip_port: fields.sipPort.trim() || "5060",
      },
    };
  }

  if (channelType === "api") {
    return { api_key: fields.apiKey.trim() || undefined };
  }

  if (channelType === "web_widget") {
    return {};
  }

  throw new Error("Неизвестный тип канала.");
}

export function ChannelConfigModal({
  open,
  botId,
  channel,
  status,
  onClose,
  onSaved,
}: ChannelConfigModalProps) {
  const { showToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [qrOpen, setQrOpen] = useState(false);

  const [token, setToken] = useState("");
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [businessAccountId, setBusinessAccountId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [sipServer, setSipServer] = useState("");
  const [sipLogin, setSipLogin] = useState("");
  const [sipPassword, setSipPassword] = useState("");
  const [sipPort, setSipPort] = useState("5060");

  useEffect(() => {
    if (!open) {
      setError(null);
      setSaving(false);
      setQrOpen(false);
      setToken("");
      setApiId("");
      setApiHash("");
      setPhone("");
      setApiKey("");
      setReferenceId("");
      setInstanceId("");
      setPhoneNumberId("");
      setBusinessAccountId("");
      setAccessToken("");
      setVerifyToken("");
      setSipServer("");
      setSipLogin("");
      setSipPassword("");
      setSipPort("5060");
    }
  }, [open]);

  const channelType = channel?.id ?? null;
  const connected = isHubChannelConnected(status);
  const embedScript =
    typeof status?.meta_data?.embed_script === "string"
      ? status.meta_data.embed_script
      : `<script src="${typeof window !== "undefined" ? window.location.origin : ""}/widget.js?id=${botId}" async></script>`;

  const persistAndConnect = useCallback(async () => {
    if (!channelType) return;

    setError(null);

    const secretChannels: HubChannelType[] = [
      "telegram",
      "telegram_business",
      "wazzup",
      "whatsapp_qr",
      "instagram",
      "waba",
      "calls",
    ];
    const enteredSecret =
      token.trim() ||
      apiKey.trim() ||
      accessToken.trim() ||
      instanceId.trim() ||
      referenceId.trim() ||
      phoneNumberId.trim() ||
      sipLogin.trim() ||
      sipPassword.trim();
    if (connected && secretChannels.includes(channelType) && !enteredSecret) {
      onClose();
      return;
    }

    let payload: ChannelConnectRequest;
    try {
      payload = buildConnectPayload(channelType, {
        token,
        apiId,
        apiHash,
        phone,
        apiKey,
        referenceId,
        instanceId,
        phoneNumberId,
        businessAccountId,
        accessToken,
        verifyToken,
        sipServer,
        sipLogin,
        sipPassword,
        sipPort,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Проверьте поля подключения.";
      setError(message);
      showToast(message, "error");
      return;
    }

    setSaving(true);
    try {
      const response = await connectHubChannel(botId, channelType, payload);
      await patchHubChannelEnabled(botId, channelType, true);
      showToast(response.message || "Канал подключён.", "success");
      onSaved();
      onClose();
    } catch (err) {
      const message = getApiErrorMessage(err, "Не удалось сохранить настройки канала.");
      setError(message);
      showToast(message, "error");
    } finally {
      setSaving(false);
    }
  }, [
    accessToken,
    apiHash,
    apiId,
    apiKey,
    botId,
    businessAccountId,
    channelType,
    connected,
    instanceId,
    onClose,
    onSaved,
    phone,
    phoneNumberId,
    referenceId,
    showToast,
    sipLogin,
    sipPassword,
    sipPort,
    sipServer,
    token,
    verifyToken,
  ]);

  const handleDisconnect = async (): Promise<void> => {
    if (!channelType) return;
    setSaving(true);
    try {
      const response = await disconnectHubChannel(botId, channelType);
      showToast(response.message, "success");
      onSaved();
      onClose();
    } catch (err) {
      showToast(getApiErrorMessage(err, "Не удалось отключить канал."), "error");
    } finally {
      setSaving(false);
    }
  };

  if (!open || !channel) return null;

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <button
          type="button"
          className="absolute inset-0 bg-black/75 backdrop-blur-sm"
          onClick={onClose}
          aria-label="Закрыть"
        />
        <div className="moonai-modal relative z-10 flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden">
          <div className="flex items-start justify-between gap-3 border-b border-zinc-800/80 px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold text-zinc-50">{channel.label}</h2>
              <p className="mt-1 text-sm text-zinc-500">{channel.description}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
            {error ? (
              <p
                role="alert"
                className="rounded-lg border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-sm text-rose-300"
              >
                {error}
              </p>
            ) : null}

            {channelType === "telegram" ? (
              <Field label="Токен бота (@BotFather)" value={token} onChange={setToken} password />
            ) : null}

            {channelType === "telegram_business" ? (
              <>
                <Field label="API ID" value={apiId} onChange={setApiId} />
                <Field label="API Hash" value={apiHash} onChange={setApiHash} password />
                <Field
                  label="Номер телефона"
                  value={phone}
                  onChange={setPhone}
                  placeholder="+77001234567"
                />
                <Field
                  label="Bot Token (опционально)"
                  value={token}
                  onChange={setToken}
                  password
                />
              </>
            ) : null}

            {channelType === "wazzup" ? (
              <>
                <Field label="API Key" value={apiKey} onChange={setApiKey} password />
                <Field label="Channel ID" value={referenceId} onChange={setReferenceId} />
              </>
            ) : null}

            {channelType === "whatsapp_qr" ? (
              <>
                <p className="text-sm text-zinc-400">
                  Подключите номер через Green API (Instance ID + API Token) или отсканируйте
                  QR-код в WhatsApp.
                </p>
                <Field
                  label="Instance ID"
                  value={instanceId}
                  onChange={setInstanceId}
                  placeholder="1101xxxxxxxx"
                />
                <Field label="API Token" value={apiKey} onChange={setApiKey} password />
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    setQrOpen(true);
                  }}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm font-medium text-emerald-200 hover:bg-emerald-500/15"
                >
                  <QrCode className="h-4 w-4" />
                  Подключить по QR-коду
                </button>
              </>
            ) : null}

            {channelType === "instagram" ? (
              <>
                <p className="text-sm text-zinc-400">
                  Instagram Direct через Green API: Instance ID и API Token инстанса.
                </p>
                <Field
                  label="Instance ID"
                  value={instanceId}
                  onChange={setInstanceId}
                  placeholder="1101xxxxxxxx"
                />
                <Field label="API Token" value={apiKey} onChange={setApiKey} password />
              </>
            ) : null}

            {channelType === "waba" ? (
              <>
                <Field label="Phone Number ID" value={phoneNumberId} onChange={setPhoneNumberId} />
                <Field
                  label="Access Token"
                  value={accessToken}
                  onChange={setAccessToken}
                  password
                />
                <Field
                  label="Business Account ID (опционально)"
                  value={businessAccountId}
                  onChange={setBusinessAccountId}
                />
                <Field
                  label="Verify Token"
                  value={verifyToken}
                  onChange={setVerifyToken}
                  placeholder="Опционально — сгенерируем автоматически"
                />
              </>
            ) : null}

            {channelType === "calls" ? (
              <>
                <Field
                  label="SIP Server"
                  value={sipServer}
                  onChange={setSipServer}
                  placeholder="sip.pbx.example.com"
                />
                <Field label="Login" value={sipLogin} onChange={setSipLogin} />
                <Field
                  label="Password"
                  value={sipPassword}
                  onChange={setSipPassword}
                  password
                />
                <Field label="Port" value={sipPort} onChange={setSipPort} placeholder="5060" />
              </>
            ) : null}

            {channelType === "api" ? (
              <>
                <p className="text-sm text-zinc-400">
                  Оставьте ключ пустым — сервер сгенерирует API-ключ и webhook URL.
                </p>
                <Field
                  label="API Key (оставьте пустым — сгенерируем)"
                  value={apiKey}
                  onChange={setApiKey}
                  password
                />
                {status?.webhook_url ? (
                  <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                    <p className="mb-1 text-[10px] uppercase tracking-wide text-zinc-500">
                      Webhook URL
                    </p>
                    <code className="block break-all font-mono text-[11px] text-zinc-300">
                      {status.webhook_url}
                    </code>
                  </div>
                ) : null}
              </>
            ) : null}

            {channelType === "web_widget" ? (
              connected ? (
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-3">
                  <p className="mb-2 text-xs font-medium text-zinc-400">Скрипт для сайта</p>
                  <code className="block whitespace-pre-wrap break-all font-mono text-[11px] text-violet-200">
                    {embedScript}
                  </code>
                </div>
              ) : (
                <p className="text-sm text-zinc-400">
                  Нажмите «Сохранить и подключить» — будет сгенерирован embed-скрипт для вставки
                  на сайт.
                </p>
              )
            ) : null}

            {status?.webhook_url && channelType !== "api" ? (
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-3">
                <p className="mb-1 text-[10px] uppercase tracking-wide text-zinc-500">Webhook</p>
                <code className="block break-all font-mono text-[11px] text-zinc-400">
                  {status.webhook_url}
                </code>
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-800/80 px-5 py-4">
            {connected ? (
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleDisconnect()}
                className="rounded-xl border border-rose-900/60 px-4 py-2.5 text-sm text-rose-300 hover:bg-rose-950/40 disabled:opacity-50"
              >
                Отключить
              </button>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-zinc-800 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-900"
            >
              Отмена
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void persistAndConnect()}
              className={cn(
                "inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50",
              )}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {connected ? "Сохранить" : "Сохранить и подключить"}
            </button>
          </div>
        </div>
      </div>

      <WhatsAppQrModal
        botId={botId}
        open={qrOpen}
        onClose={() => setQrOpen(false)}
        onConnected={() => {
          setQrOpen(false);
          onSaved();
          onClose();
        }}
      />
    </>
  );
}
