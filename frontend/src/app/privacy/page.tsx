import { LegalDocument } from "@/components/legal/LegalDocument";
import { COMPANY, companyLine } from "@/lib/company";
import { supportEmail } from "@/lib/support-email";

export default function PrivacyPage() {
  const email = supportEmail();
  return (
    <LegalDocument
      title="Политика конфиденциальности"
      updated="Обновлено: 8 сентября 2026. Документ для юридического ревью перед публичным GA."
    >
      <p>
        Оператор платформы {COMPANY.brand}: {companyLine()}. Контакты по вопросам персональных
        данных:{" "}
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>
        . Юрисдикция: {COMPANY.jurisdiction}.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">1. Какие данные обрабатываем</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>учётные: email, имя, хеш пароля, роли в организации;</li>
        <li>данные организации: название, участники, настройки workspace;</li>
        <li>контент сервиса: промпты, сценарии, база знаний, переписка агентов с клиентами;</li>
        <li>секреты интеграций (токены каналов/CRM) — в зашифрованном виде;</li>
        <li>платёжные метаданные (Stripe / TipTop Pay): идентификаторы клиента, статус; полные данные карт мы не храним;</li>
        <li>технические: IP, user-agent, cookie сессии, журналы безопасности и ошибок.</li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">2. Цели и основания</h2>
      <p>
        Оказание SaaS-услуги, биллинг и квоты, безопасность, поддержка, исполнение договора и
        требований закона. Сообщения конечных пользователей обрабатываются для работы вашего
        агента по вашему поручению (вы — контролёр данных своих клиентов).
      </p>

      <h2 className="text-base font-semibold text-zinc-100">3. Сторонние сервисы</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>LLM-провайдеры (OpenAI, Groq, OpenRouter и др.) — текст запросов агента;</li>
        <li>платежи: Stripe, TipTop Pay (виджет cloudpayments);</li>
        <li>инфраструктура хостинга/БД/Redis/object storage по вашему деплою;</li>
        <li>мессенджеры и CRM, которые вы сами подключаете (Telegram, WhatsApp, Bitrix24…).</li>
      </ul>
      <p>
        Аналитические и маркетинговые cookie не включаются без согласия (см.{" "}
        <a className="text-zinc-200 underline" href="/legal/cookies">
          Политику cookie
        </a>
        ).
      </p>

      <h2 className="text-base font-semibold text-zinc-100">4. Хранение и передача</h2>
      <p>
        Данные размещаются у инфраструктурного провайдера выбранного деплоя. Мы не продаём
        персональные данные. Срок хранения — пока активен аккаунт и в пределах законных сроков
        для биллинга/безопасности (конкретные сроки — в договоре / по запросу).
      </p>

      <h2 className="text-base font-semibold text-zinc-100">5. Права субъекта</h2>
      <p>
        Доступ, исправление, удаление, ограничение обработки, отзыв согласия (где применимо):{" "}
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>
        . Срок ответа — до 30 календарных дней, если иное не требует закон.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">6. Связанные документы</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <a className="text-zinc-200 underline" href="/terms">
            Условия использования
          </a>
        </li>
        <li>
          <a className="text-zinc-200 underline" href="/legal/personal-data">
            Согласие на обработку ПДн
          </a>
        </li>
        <li>
          <a className="text-zinc-200 underline" href="/legal/cookies">
            Политика cookie
          </a>
        </li>
        <li>
          <a className="text-zinc-200 underline" href="/legal/refund">
            Политика возвратов
          </a>
        </li>
      </ul>
    </LegalDocument>
  );
}
