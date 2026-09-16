/** Incoming Webhook is ``https://portal/rest/{userId}/{code}/``, never a CRM UI page. */

export function validateBitrixIncomingWebhook(url: string): string | null {
  const trimmed = url.trim();
  if (!trimmed) {
    return "Укажите Incoming Webhook URL Bitrix24.";
  }
  if (!/^https?:\/\/.+/i.test(trimmed)) {
    return "Incoming Webhook должен начинаться с https://";
  }
  if (/\/crm\//i.test(trimmed) || /kanban/i.test(trimmed)) {
    return (
      "Это страница канбана CRM, не Incoming Webhook. В Bitrix24: Разработчикам → Другое → " +
      "Входящий вебхук (права CRM: сделки и контакты). Скопируйте URL вида " +
      "https://xxx.bitrix24.ru/rest/1/xxxxxxxx/"
    );
  }
  if (!/\/rest\/\d+\/[^/\s?#]+/i.test(trimmed)) {
    return (
      "Укажите Incoming Webhook URL вида https://xxx.bitrix24.ru/rest/1/xxxxxxxx/. " +
      "Страница портала или канбан не подойдут."
    );
  }
  return null;
}

export function normalizeBitrixIncomingWebhook(url: string): string {
  const trimmed = url.trim();
  const match = trimmed.match(/https?:\/\/[^/\s]+\/rest\/\d+\/[^/\s?#]+/i);
  const base = match ? match[0] : trimmed;
  return base.endsWith("/") ? base : `${base}/`;
}
