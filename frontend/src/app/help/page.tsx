import Link from "next/link";

import { SiteFooter } from "@/components/legal/SiteFooter";

export default function HelpPage() {
  return (
    <div className="min-h-screen bg-[#050507] text-zinc-200">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <Link href="/dashboard" className="text-xs text-zinc-500 hover:text-zinc-300">
          ← Дашборд
        </Link>
        <h1 className="mt-6 text-3xl font-semibold text-zinc-50">Справка MP.AI</h1>
        <p className="mt-2 text-sm text-zinc-500">
          Краткие гайды для запуска агента, оплаты и каналов.
        </p>

        <section className="mt-10 space-y-3">
          <h2 className="text-lg font-semibold text-zinc-100">Конструктор сценариев</h2>
          <ol className="list-decimal space-y-2 pl-5 text-sm text-zinc-400">
            <li>
              Создайте агента на дашборде или из{" "}
              <Link href="/dashboard/templates" className="text-zinc-200 underline">
                галереи шаблонов
              </Link>
              .
            </li>
            <li>
              Откройте <strong className="text-zinc-200">Конструктор</strong> и соедините
              Trigger → текст / LLM / RAG → Publish.
            </li>
            <li>Проверьте ответ в Preview, затем подключите канал.</li>
          </ol>
        </section>

        <section className="mt-8 space-y-3">
          <h2 className="text-lg font-semibold text-zinc-100">Биллинг</h2>
          <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-400">
            <li>
              Кошелёк и тарифы:{" "}
              <Link href="/dashboard/billing" className="text-zinc-200 underline">
                /dashboard/billing
              </Link>
              .
            </li>
            <li>Пополнение — Stripe Checkout или TipTop (если включены ключи).</li>
            <li>
              При исчерпании квоты API отвечает <code>402</code>. В ответе есть{" "}
              <code>correlation_id</code> для поддержки.
            </li>
          </ul>
        </section>

        <section className="mt-8 space-y-3">
          <h2 className="text-lg font-semibold text-zinc-100">Ещё</h2>
          <p className="text-sm text-zinc-400">
            <Link href="/support" className="text-zinc-200 underline">
              Контакты поддержки
            </Link>
            {" · "}
            <Link href="/legal/limitations" className="text-zinc-200 underline">
              Ограничения v1
            </Link>
          </p>
        </section>
      </div>
      <SiteFooter />
    </div>
  );
}
