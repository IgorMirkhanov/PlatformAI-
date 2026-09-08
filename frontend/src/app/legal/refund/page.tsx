import { LegalDocument } from "@/components/legal/LegalDocument";
import { COMPANY, companyLine } from "@/lib/company";
import { supportEmail } from "@/lib/support-email";

export default function RefundPolicyPage() {
  const email = supportEmail();
  return (
    <LegalDocument title="Политика возврата средств" updated="Обновлено: 8 сентября 2026.">
      <p>
        Оператор: {companyLine()}. Политика описывает порядок возвратов за услуги платформы{" "}
        {COMPANY.brand} (цифровой SaaS).
      </p>

      <h2 className="text-base font-semibold text-zinc-100">1. Общие правила</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          Услуги считаются оказанными по факту предоставления доступа к платформе и/или списания
          кредитов кошелька / подписки за период.
        </li>
        <li>
          Возврат неиспользованного остатка кредитов или пропорциональной части подписки возможен
          при подтверждённом техническом сбое на стороне оператора, препятствовавшем использованию
          оплаченной услуги, либо в случаях, прямо предусмотренных договором / законом.
        </li>
        <li>
          Платежи, проведённые через Stripe или TipTop Pay, также подчиняются правилам
          соответствующего провайдера и банка-эмитента.
        </li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">2. Как запросить возврат</h2>
      <p>
        Напишите на{" "}
        <a className="text-zinc-200 underline" href={`mailto:${email}`}>
          {email}
        </a>{" "}
        с темой «Возврат», укажите email аккаунта, организацию, дату платежа, сумму и причину.
        Срок рассмотрения — до 10 рабочих дней.
      </p>

      <h2 className="text-base font-semibold text-zinc-100">3. Отказ в возврате</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>услуга использована (агенты отвечали, кредиты списаны за LLM/каналы);</li>
        <li>нарушение условий использования / злоупотребление;</li>
        <li>сбои внешних LLM, мессенджеров или CRM вне контроля оператора (см. ограничения v1).</li>
      </ul>

      <h2 className="text-base font-semibold text-zinc-100">4. Способ возврата</h2>
      <p>
        На тот же платёжный инструмент / по реквизитам, согласованным с бухгалтерией. Комиссии
        банка могут удерживаться, если это допускает применимое право и договор с провайдером.
      </p>
    </LegalDocument>
  );
}
