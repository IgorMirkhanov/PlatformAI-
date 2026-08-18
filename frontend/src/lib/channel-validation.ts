import type { ApiValidationIssue } from "@/lib/api";
import type {
  InstagramChannelFormValues,
  TelegramChannelFormValues,
  VkontakteChannelFormValues,
  WhatsAppChannelFormValues,
} from "@/types/channels";

export type FieldErrors<T extends string> = Partial<Record<T, string>>;

const TELEGRAM_TOKEN_PATTERN = /^\d{8,12}:[A-Za-z0-9_-]{30,}$/;

/** First validation error message for crimson banner display. */
export function firstValidationError(errors: Record<string, string>): string | null {
  const values = Object.values(errors).filter(Boolean);
  return values[0] ?? null;
}

export function validateHubTelegramToken(token: string): string | null {
  const value = token.trim();
  if (!value) {
    return "Укажите токен бота от @BotFather.";
  }
  if (!TELEGRAM_TOKEN_PATTERN.test(value)) {
    return "Неверный формат токена. Пример: 123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
  }
  return null;
}

export function validateHubWabaForm(values: {
  phone_number_id: string;
  business_account_id: string;
  access_token: string;
  verify_token?: string;
}): string | null {
  if (!values.phone_number_id.trim()) {
    return "Phone Number ID обязателен.";
  }
  if (!/^\d{5,}$/.test(values.phone_number_id.trim())) {
    return "Phone Number ID должен содержать только цифры.";
  }
  if (!values.business_account_id.trim()) {
    return "Business Account ID обязателен.";
  }
  if (!/^\d{5,}$/.test(values.business_account_id.trim())) {
    return "Business Account ID должен содержать только цифры.";
  }
  if (!values.access_token.trim()) {
    return "Access Token обязателен.";
  }
  if (values.access_token.trim().length < 20) {
    return "Access Token слишком короткий.";
  }
  if (values.verify_token?.trim() && values.verify_token.trim().length < 8) {
    return "Verify Token должен быть не короче 8 символов.";
  }
  return null;
}

export function validateHubWazzupForm(values: { api_key: string }): string | null {
  if (!values.api_key.trim()) {
    return "Укажите API-ключ Wazzup.";
  }
  if (values.api_key.trim().length < 16) {
    return "API-ключ Wazzup слишком короткий.";
  }
  return null;
}

export function validateHubInstagramForm(values: {
  page_id: string;
  access_token: string;
}): string | null {
  if (!values.page_id.trim()) {
    return "Page ID обязателен.";
  }
  if (!/^\d{5,}$/.test(values.page_id.trim())) {
    return "Page ID должен содержать только цифры.";
  }
  if (!values.access_token.trim()) {
    return "Access Token обязателен.";
  }
  if (values.access_token.trim().length < 20) {
    return "Access Token слишком короткий.";
  }
  return null;
}

export function validateTelegramForm(
  values: TelegramChannelFormValues,
): FieldErrors<keyof TelegramChannelFormValues> {
  const errors: FieldErrors<keyof TelegramChannelFormValues> = {};
  const tokenError = validateHubTelegramToken(values.telegram_bot_token);
  if (tokenError) {
    errors.telegram_bot_token = tokenError;
  }
  return errors;
}

export function validateWhatsAppForm(
  values: WhatsAppChannelFormValues,
): FieldErrors<keyof WhatsAppChannelFormValues> {
  const errors: FieldErrors<keyof WhatsAppChannelFormValues> = {};
  const banner = validateHubWabaForm({
    phone_number_id: values.whatsapp_phone_number_id,
    business_account_id: values.whatsapp_business_account_id,
    access_token: values.whatsapp_access_token,
    verify_token: values.whatsapp_verify_token,
  });
  if (banner) {
    if (banner.includes("Phone Number")) {
      errors.whatsapp_phone_number_id = banner;
    } else if (banner.includes("Business Account") || banner.includes("WABA")) {
      errors.whatsapp_business_account_id = banner;
    } else if (banner.includes("Verify")) {
      errors.whatsapp_verify_token = banner;
    } else {
      errors.whatsapp_access_token = banner;
    }
  }
  return errors;
}

export function validateInstagramForm(
  values: InstagramChannelFormValues,
): FieldErrors<keyof InstagramChannelFormValues> {
  const errors: FieldErrors<keyof InstagramChannelFormValues> = {};
  const banner = validateHubInstagramForm({
    page_id: values.instagram_page_id,
    access_token: values.instagram_access_token,
  });
  if (banner) {
    if (banner.includes("Page ID")) {
      errors.instagram_page_id = banner;
    } else {
      errors.instagram_access_token = banner;
    }
  }
  return errors;
}

export function validateVkontakteForm(
  values: VkontakteChannelFormValues,
): FieldErrors<keyof VkontakteChannelFormValues> {
  const errors: FieldErrors<keyof VkontakteChannelFormValues> = {};

  const groupId = values.vk_group_id.trim();
  if (!groupId) {
    errors.vk_group_id = "ID сообщества обязателен.";
  } else if (!/^-?\d+$/.test(groupId)) {
    errors.vk_group_id = "ID сообщества должен быть числом (можно с минусом).";
  }

  if (!values.vk_access_token.trim()) {
    errors.vk_access_token = "Access Token сообщества обязателен.";
  } else if (values.vk_access_token.trim().length < 20) {
    errors.vk_access_token = "Access Token слишком короткий.";
  }

  return errors;
}

interface PydanticErrorItem {
  loc?: (string | number)[];
  msg?: string;
}

function normalizeFieldKey(loc: (string | number)[] | undefined): string | null {
  if (!loc || loc.length === 0) {
    return null;
  }
  const field = loc[loc.length - 1];
  return typeof field === "string" ? field : null;
}

export function mapApiIssuesToFieldErrors(
  issues: ApiValidationIssue[],
  detail?: unknown,
): Record<string, string> {
  const fieldErrors: Record<string, string> = {};

  for (const issue of issues) {
    if (issue.field) {
      fieldErrors[issue.field] = issue.message;
    }
  }

  if (Array.isArray(detail)) {
    for (const item of detail as PydanticErrorItem[]) {
      const key = normalizeFieldKey(item.loc);
      if (key && item.msg) {
        fieldErrors[key] = item.msg;
      }
    }
  }

  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const nested = detail as { issues?: ApiValidationIssue[] };
    if (Array.isArray(nested.issues)) {
      for (const issue of nested.issues) {
        if (issue.field) {
          fieldErrors[issue.field] = issue.message;
        }
      }
    }
  }

  return fieldErrors;
}

export function hasFieldErrors(errors: Record<string, string>): boolean {
  return Object.keys(errors).length > 0;
}
