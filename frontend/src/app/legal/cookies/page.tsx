import { LegalDocument } from "@/components/legal/LegalDocument";
import { COMPANY, companyLine } from "@/lib/company";
import { supportEmail } from "@/lib/support-email";

export default function CookiesPolicyPage() {
  const email = supportEmail();
  return (
    <LegalDocument
      title="Политика файлов cookie"
      updated="Обновлено: 8 сентября 2026."
    >
      <p>
        Оператор: {companyLine()}. Эта политика объясняет, какие cookie и похожие технологии
        использует {COMPANY.brand}, и как управлять согласием.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">1. Категории</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <strong className="text-zinc-200">Необходимые</strong> — вход, сессия, CSRF/безопасность,
          выбор темы, сохранение выбора согласия. Без них сервис не работает.
        </li>
        <li>
          <strong className="text-zinc-200">Аналитические</strong> — измерение использования (если
          подключены). Включаются только после согласия «Принять все» или отдельной настройки.
        </li>
        <li>
          <strong className="text-zinc-200">Маркетинговые</strong> — сейчас по умолчанию не
          используются; при появлении — только с согласия.
        </li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">2. Примеры необходимых</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <code className="text-zinc-300">mpai_access_token</code> / связанные cookie сессии —
          аутентификация;
        </li>
        <li>локальное хранилище согласия cookie (<code className="text-zinc-300">mpai_cookie_consent_v1</code>);</li>
        <li>настройки темы интерфейса.</li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">3. Платежный виджет</h2>
      <p>
        Скрипт TipTop Pay / CloudPayments загружается для оплаты счетов. Это функциональный
        компонент биллинга, а не рекламный трекер. Обработка платёжных данных — у провайдера.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">4. Управление</h2>
      <p>
        Баннер согласия появляется при первом визите. Сбросить выбор можно очисткой данных сайта
        в браузере или запросом на{" "}
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>
        . См. также{" "}
        <a className="text-zinc-200 underline" href="/privacy">
          Политику конфиденциальности
        </a>
        .
      </p>
    </LegalDocument>
  );
}
