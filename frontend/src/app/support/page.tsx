import { LegalDocument } from "@/components/legal/LegalDocument";
import { supportEmail } from "@/lib/support-email";

export default function SupportPage() {
  const email = supportEmail();
  return (
    <LegalDocument title="Поддержка">
      <p>
        Письма:{" "}
        <a className="text-zinc-100 underline" href={`mailto:${email}`}>
          {email}
        </a>
        . В теме укажите организацию, bot id и <code>X-Correlation-ID</code> из ошибочного
        ответа API — так мы быстрее найдём запрос в логах.
      </p>
      <h2 className="text-base font-semibold text-zinc-100">SLA soft-launch</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>рабочие часы: пн–пт 10:00–19:00 (Asia/Almaty);</li>
        <li>Sev-0 (платформа недоступна): реакция в течение 2 часов в окне дежурства;</li>
        <li>остальные инциденты: следующий рабочий день.</li>
      </ul>
      <p>
        Руководства:{" "}
        <a className="text-zinc-200 underline" href="/help">
          /help
        </a>{" "}
        (публично) и{" "}
        <a className="text-zinc-200 underline" href="/dashboard/help">
          /dashboard/help
        </a>{" "}
        в приложении.
      </p>
    </LegalDocument>
  );
}
