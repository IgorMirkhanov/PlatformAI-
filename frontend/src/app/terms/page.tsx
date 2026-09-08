import { LegalDocument } from "@/components/legal/LegalDocument";
import { COMPANY, companyLine } from "@/lib/company";
import { supportEmail } from "@/lib/support-email";

export default function TermsPage() {
  const email = supportEmail();
  return (
    <LegalDocument
      title="Условия использования"
      updated="Обновлено: 8 сентября 2026. Документ для юридического ревью перед публичным GA."
    >
      <p>
        Договор присоединения к сервису {COMPANY.brand}. Оператор: {companyLine()}. Регистрируясь,
        вы подтверждаете полномочия заключать договор от имени организации и согласие с этими
        условиями,{" "}
        <a className="text-zinc-200 underline" href="/privacy">
          Политикой конфиденциальности
        </a>{" "}
        и{" "}
        <a className="text-zinc-200 underline" href="/legal/personal-data">
          согласием на обработку ПДн
        </a>
        .
      </p>

      <h2 className="text-base font-semibold text-zinc-100">1. Сервис</h2>
      <p>
        {COMPANY.brand} — платформа для создания и запуска ИИ-агентов в мессенджерах, CRM и
        виджетах. Функции, квоты и тарифы отображаются в биллинге workspace. Существенные
        изменения оплаченного периода сообщаются заранее, где это разумно возможно.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">2. Допустимое использование</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>запрещены спам, мошенничество, вредоносный код, обход квот и незаконный контент;</li>
        <li>вы отвечаете за контент агента и наличие законных оснований для обработки данных конечных пользователей;</li>
        <li>секреты каналов хранятся только в вашем workspace и не должны передаваться третьим лицам.</li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">3. Оплата и возвраты</h2>
      <p>
        Списания — с кошелька организации и/или через Stripe / TipTop Pay. При исчерпании квоты
        API может вернуть HTTP 402. Возвраты регулируются{" "}
        <a className="text-zinc-200 underline" href="/legal/refund">
          Политикой возвратов
        </a>{" "}
        и правилами платёжного провайдера.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">4. Интеллектуальная собственность</h2>
      <p>
        Платформа и её ПО принадлежат оператору. Контент, который вы загружаете (промпты, базы
        знаний, сценарии), остаётся вашим; вы даёте нам лицензию на обработку для оказания
        услуги. Иконки UI — Lucide (ISC). Стоковые изображения на лендинге не используются.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">5. Ограничение ответственности</h2>
      <p>
        Сервис предоставляется «как есть». Мы не гарантируем непрерывность внешних LLM и
        мессенджеров. Маркетинговые метрики на сайте не являются SLA, если SLA не согласован
        письменно. Известные ограничения:{" "}
        <a className="text-zinc-200 underline" href="/legal/limitations">
          /legal/limitations
        </a>
        .
      </p>

      <h2 className="text-base font-semibold text-zinc-100">6. Контакты</h2>
      <p>
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>
        · {COMPANY.city}
      </p>
    </LegalDocument>
  );
}
