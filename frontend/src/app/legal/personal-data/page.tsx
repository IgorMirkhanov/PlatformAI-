import { LegalDocument } from "@/components/legal/LegalDocument";
import { COMPANY, companyLine } from "@/lib/company";
import { supportEmail } from "@/lib/support-email";

export default function PersonalDataConsentPage() {
  const email = supportEmail();
  return (
    <LegalDocument
      title="Согласие на обработку персональных данных"
      updated="Обновлено: 8 сентября 2026."
    >
      <p>
        Настоящим субъект персональных данных (далее — «Субъект») даёт согласие оператору{" "}
        {companyLine()} на обработку персональных данных на условиях ниже и{" "}
        <a className="text-zinc-200 underline" href="/privacy">
          Политики конфиденциальности
        </a>
        .
      </p>

      <h2 className="text-base font-semibold text-zinc-100">1. Состав данных</h2>
      <p>
        Фамилия, имя, отчество (при наличии), email, телефон (если указан), данные организации,
        технические данные устройства и журналы использования сервиса {COMPANY.brand}.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">2. Цели</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>регистрация и обслуживание аккаунта / workspace;</li>
        <li>оказание SaaS-услуг, биллинг, поддержка;</li>
        <li>безопасность, предотвращение злоупотреблений;</li>
        <li>исполнение требований законодательства РК и применимых норм.</li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">3. Действия с данными</h2>
      <p>
        Сбор, запись, систематизация, хранение, уточнение, использование, передача (в объёме,
        необходимом провайдерам инфраструктуры, LLM и платежей), обезличивание, блокирование,
        удаление.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">4. Срок и отзыв</h2>
      <p>
        Согласие действует до удаления аккаунта или отзыва. Отзыв:{" "}
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>
        . Отзыв может сделать невозможным дальнейшее использование сервиса, если обработка
        необходима для договора.
      </p>

      <p className="text-xs text-zinc-500">
        При регистрации в интерфейсе требуется явная отметка согласия (чекбокс). Текст согласия
        подлежит финальному согласованию с юристом оператора.
      </p>
    </LegalDocument>
  );
}
