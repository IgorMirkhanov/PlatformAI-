import { LegalDocument } from "@/components/legal/LegalDocument";

export default function LimitationsPage() {
  return (
    <LegalDocument title="Известные ограничения v1">
      <p>
        Soft-launch MP.AI v1.0. Ниже — функции, которые ещё не являются production-complete.
        Это не скрытые дефекты: они задокументированы, чтобы не обещать GA-уровень там, где
        его нет.
      </p>
      <ul className="list-disc space-y-2 pl-5">
        <li>
          <strong className="text-zinc-200">Сброс пароля по email</strong> — письмо пишется в
          логи сервера, пока не подключён SMTP. Используйте суперadmin или ротацию пароля
          вручную.
        </li>
        <li>
          <strong className="text-zinc-200">OAuth-логин</strong> отключён в production
          (<code>ALLOW_OAUTH_STUB=false</code>). Вход — email + пароль.
        </li>
        <li>
          <strong className="text-zinc-200">Demo / soft-launch auth</strong> запрещён в
          production (<code>ALLOW_SOFT_LAUNCH_AUTH=false</code>).
        </li>
        <li>
          <strong className="text-zinc-200">LLM и эмбеддинги</strong> зависят от ключей
          провайдера. При отсутствии embedding-ключа RAG пропускается, чат не падает.
        </li>
        <li>
          <strong className="text-zinc-200">Квоты</strong> при исчерпании средств возвращают
          HTTP 402; диалоги в мессенджере получают мягкое сообщение вместо 500.
        </li>
        <li>
          <strong className="text-zinc-200">Совместное редактирование flow</strong> в реальном
          времени не входит в v1 — публикуйте ревизии по очереди.
        </li>
      </ul>
    </LegalDocument>
  );
}
