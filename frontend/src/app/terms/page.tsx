import { LegalDocument } from "@/components/legal/LegalDocument";
import { supportEmail } from "@/components/legal/SiteFooter";

export default function TermsPage() {
  const email = supportEmail();
  return (
    <LegalDocument title="Условия использования">
      <p>Дата публикации: 24 августа 2026. Шаблон для юридического ревью перед GA.</p>
      <p>
        Регистрируясь в MP.AI, вы подтверждаете, что имеете право заключать договор от имени
        организации и обязуетесь соблюдать эти условия.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">Сервис</h2>
      <p>
        MP.AI — платформа для создания и запуска ИИ-агентов в мессенджерах, CRM и виджетах.
        Функции, квоты и тарифы описаны в биллинге workspace. Мы можем менять продукт с
        уведомлением, если изменение существенно влияет на оплаченный период.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">Допустимое использование</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>запрещены спам, мошенничество, вредоносный код и обход квот;</li>
        <li>вы отвечаете за контент агента и согласие конечных пользователей;</li>
        <li>секреты каналов (токены Telegram, Wazzup, CRM) хранятся только в вашем workspace.</li>
      </ul>
      <h2 className="text-base font-semibold text-zinc-100">Оплата</h2>
      <p>
        Списания идут с кошелька организации и/или через Stripe / TipTop. При исчерпании
        квоты API возвращает HTTP 402. Возвраты — по правилам платёжного провайдера и
        письменному обращению на {email}.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">Ограничение ответственности</h2>
      <p>
        Сервис предоставляется «как есть». Мы не гарантируем непрерывность ответов внешних
        LLM и мессенджеров. Известные ограничения v1 описаны на странице{" "}
        <a className="text-zinc-200 underline" href="/legal/limitations">
          /legal/limitations
        </a>
        .
      </p>
    </LegalDocument>
  );
}
