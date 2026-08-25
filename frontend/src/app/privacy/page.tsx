import { LegalDocument } from "@/components/legal/LegalDocument";
import { supportEmail } from "@/components/legal/SiteFooter";

export default function PrivacyPage() {
  const email = supportEmail();
  return (
    <LegalDocument title="Политика конфиденциальности">
      <p>Дата публикации: 24 августа 2026. Шаблон для юридического ревью перед GA.</p>
      <p>
        MP.AI («мы») обрабатывает данные, которые вы передаёте при регистрации, работе с
        агентами, каналами связи и биллингом. Контролёр — организация, указанная в договоре
        или в аккаунте workspace.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">Какие данные собираем</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>учётные данные: email, имя, хеш пароля;</li>
        <li>данные организации: название, участники, роли;</li>
        <li>контент ботов: промпты, сценарии, база знаний, переписка с клиентами;</li>
        <li>токены каналов и CRM — в зашифрованном виде (AES-256-GCM);</li>
        <li>платёжные метаданные (Stripe / TipTop): идентификаторы клиента, статус подписки. Полные данные карты мы не храним.</li>
      </ul>
      <h2 className="text-base font-semibold text-zinc-100">Цели</h2>
      <p>
        Оказание SaaS-услуги, биллинг, безопасность, поддержка, соблюдение закона. Сообщения
        конечных пользователей обрабатываются только для работы вашего агента.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">Хранение и передача</h2>
      <p>
        Данные размещаются у инфраструктурного провайдера, который вы выбрали при деплое.
        Провайдеры LLM (OpenAI, Groq, OpenRouter и др.) получают только тот текст, который
        агент отправляет в запросе. Мы не продаём персональные данные.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">Права</h2>
      <p>
        Запрос на доступ, исправление или удаление:{" "}
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>
        . Срок ответа — до 30 дней.
      </p>
    </LegalDocument>
  );
}
