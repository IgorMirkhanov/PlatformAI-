"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Bot,
  Cpu,
  GitBranch,
  MessageSquare,
  Radio,
  Sparkles,
  Workflow,
  Zap,
} from "lucide-react";

import {
  CHANGELOG_IN_PROGRESS,
  CHANGELOG_RELEASED,
  MICROSERVICES,
  SYSTEM_METRICS,
  type ChangelogEntry,
  type ChangelogStatus,
} from "@/components/landing/gateway-data";
import { buildApiUrl } from "@/lib/api/baseUrl";
import { getAccessToken } from "@/lib/auth/tokens";
import { cn } from "@/lib/utils";

type ServiceHealth = "online" | "degraded" | "checking";

function StatusDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex h-2.5 w-2.5", className)}>
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-40" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
    </span>
  );
}

function ChangelogBadge({ status }: { status: ChangelogStatus }) {
  const styles: Record<ChangelogStatus, string> = {
    released: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    in_progress: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
    planned: "border-zinc-600 bg-zinc-800/50 text-zinc-400",
  };
  const labels: Record<ChangelogStatus, string> = {
    released: "Релиз",
    in_progress: "В разработке",
    planned: "План",
  };
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        styles[status],
      )}
    >
      {labels[status]}
    </span>
  );
}

function ChangelogCard({ entry }: { entry: ChangelogEntry }) {
  return (
    <article className="group rounded-2xl border border-[#1f2430] bg-[#0e1017] p-5 transition-all duration-300 hover:border-purple-500/30 hover:shadow-glow-purple">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ChangelogBadge status={entry.status} />
        {entry.version ? (
          <span className="font-mono text-[11px] text-zinc-500">{entry.version}</span>
        ) : null}
      </div>
      <h3 className="mt-3 text-base font-semibold text-zinc-50 transition-colors group-hover:text-purple-200">
        {entry.title}
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-zinc-400">{entry.description}</p>
      {entry.date ? <p className="mt-3 text-xs text-zinc-600">{entry.date}</p> : null}
    </article>
  );
}

export function GatewayLandingPage() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [platformOnline, setPlatformOnline] = useState<ServiceHealth>("checking");
  const [serviceHealth, setServiceHealth] = useState<Record<string, ServiceHealth>>({
    llm: "checking",
    flow: "checking",
    omni: "checking",
  });
  const [lastPing, setLastPing] = useState<string>("—");

  useEffect(() => {
    setIsAuthenticated(Boolean(getAccessToken()));
  }, []);

  useEffect(() => {
    let cancelled = false;

    const pingPlatform = async () => {
      const started = performance.now();
      try {
        const response = await fetch(buildApiUrl("/api/v1/health/live"), {
          method: "GET",
          cache: "no-store",
        });
        if (cancelled) return;
        const elapsed = Math.round(performance.now() - started);
        const online = response.ok;
        setPlatformOnline(online ? "online" : "degraded");
        setLastPing(`${elapsed}ms`);
        setServiceHealth({
          llm: online ? "online" : "degraded",
          flow: online ? "online" : "degraded",
          omni: online ? "online" : "degraded",
        });
      } catch {
        if (cancelled) return;
        setPlatformOnline("degraded");
        setLastPing("timeout");
        setServiceHealth({
          llm: "degraded",
          flow: "degraded",
          omni: "degraded",
        });
      }
    };

    void pingPlatform();
    const timer = window.setInterval(() => void pingPlatform(), 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const statusLabel = useMemo(() => {
    if (platformOnline === "checking") return "SYNC";
    if (platformOnline === "online") return "ONLINE";
    return "DEGRADED";
  }, [platformOnline]);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#050507] text-zinc-100">
      <div
        aria-hidden
        className="pointer-events-none absolute -left-32 top-0 h-96 w-96 rounded-full bg-purple-600/20 blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 top-40 h-80 w-80 rounded-full bg-cyan-500/10 blur-[100px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-violet-500/10 blur-[110px]"
      />

      <header className="relative z-10 border-b border-[#1f2430]/80 bg-[#050507]/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-purple-500/30 bg-purple-500/10 shadow-glow-purple">
              <Zap className="h-5 w-5 text-purple-400" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-bold tracking-tight text-white sm:text-base">
                  MP.AI <span className="text-zinc-500">//</span> Gateway
                </p>
                <StatusDot />
              </div>
              <p className="truncate font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-400/80">
                SYSTEM STATUS: {statusLabel} v2.5
              </p>
            </div>
          </div>

          <nav className="flex shrink-0 items-center gap-2 sm:gap-3">
            {isAuthenticated ? (
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-purple-600 to-violet-600 px-4 py-2 text-sm font-semibold text-white shadow-glow-purple transition-all duration-300 hover:from-purple-500 hover:to-violet-500"
              >
                Открыть платформу
                <ArrowRight className="h-4 w-4" />
              </Link>
            ) : (
              <>
                <Link
                  href="/login"
                  className="rounded-xl border border-[#1f2430] px-3 py-2 text-sm text-zinc-300 transition-all duration-300 hover:border-purple-500/40 hover:text-white sm:px-4"
                >
                  Войти
                </Link>
                <Link
                  href="/register"
                  className="rounded-xl bg-gradient-to-r from-purple-600 to-violet-600 px-3 py-2 text-sm font-semibold text-white shadow-glow-purple transition-all duration-300 hover:from-purple-500 hover:to-violet-500 sm:px-4"
                >
                  Регистрация
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="relative z-10">
        <section className="mx-auto max-w-6xl px-4 pb-16 pt-12 sm:px-6 sm:pt-16 lg:pt-20">
          <div className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-start">
            <div>
              <p className="inline-flex items-center gap-2 rounded-full border border-purple-500/25 bg-purple-500/10 px-3 py-1 text-xs font-medium text-purple-200">
                <Sparkles className="h-3.5 w-3.5" />
                MOONAI · Web3 · AI Infrastructure
              </p>
              <h1 className="mt-5 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl lg:text-5xl">
                Интеллектуальная экосистема{" "}
                <span className="bg-gradient-to-r from-purple-400 to-cyan-400 bg-clip-text text-transparent">
                  нового поколения
                </span>
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-relaxed text-zinc-400 sm:text-lg">
                MP.AI объединяет LLM-шлюзы, визуальный Flow Builder, омниканальные коннекторы и
                встроенную CRM в единой production-платформе для команд, которые строят
                AI-автоматизацию без компромиссов по безопасности и масштабу.
              </p>

              <div className="mt-8 grid gap-3 sm:grid-cols-3">
                {SYSTEM_METRICS.map((metric) => (
                  <div
                    key={metric.label}
                    className="rounded-2xl border border-[#1f2430] bg-[#0e1017] p-4 transition-all duration-300 hover:border-cyan-500/30"
                  >
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                      {metric.label}
                    </p>
                    <p className="mt-1 text-2xl font-bold text-white">{metric.value}</p>
                    <p className="mt-1 text-xs text-zinc-500">{metric.hint}</p>
                  </div>
                ))}
              </div>

              <div className="mt-8 flex flex-wrap gap-3">
                {isAuthenticated ? (
                  <Link
                    href="/dashboard"
                    className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 px-5 py-3 text-sm font-semibold text-white transition-all duration-300 hover:opacity-90"
                  >
                    Перейти в дашборд
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                ) : (
                  <>
                    <Link
                      href="/register"
                      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 px-5 py-3 text-sm font-semibold text-white transition-all duration-300 hover:opacity-90"
                    >
                      Начать бесплатно
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                    <Link
                      href="/login"
                      className="inline-flex items-center gap-2 rounded-xl border border-[#1f2430] px-5 py-3 text-sm font-medium text-zinc-300 transition-all duration-300 hover:border-purple-500/40 hover:text-white"
                    >
                      У меня уже есть аккаунт
                    </Link>
                  </>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-[#1f2430] bg-[#0e1017]/90 p-5 shadow-glow-purple backdrop-blur sm:p-6">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-400">
                    Live Mesh Status
                  </p>
                  <h2 className="mt-1 text-lg font-semibold text-white">Микросервисы</h2>
                </div>
                <div className="rounded-full border border-[#1f2430] px-3 py-1 font-mono text-[10px] text-zinc-500">
                  ping {lastPing}
                </div>
              </div>

              <ul className="mt-5 space-y-3">
                {MICROSERVICES.map((service) => {
                  const health = serviceHealth[service.id] ?? "checking";
                  return (
                    <li
                      key={service.id}
                      className="rounded-xl border border-[#1f2430] bg-[#050507]/60 p-4 transition-all duration-300 hover:border-purple-500/25"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-zinc-100">{service.name}</p>
                          <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                            {service.description}
                          </p>
                        </div>
                        <span
                          className={cn(
                            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                            health === "online" && "bg-emerald-500/10 text-emerald-300",
                            health === "degraded" && "bg-amber-500/10 text-amber-300",
                            health === "checking" && "bg-zinc-800 text-zinc-400",
                          )}
                        >
                          {health === "online"
                            ? "online"
                            : health === "degraded"
                              ? "degraded"
                              : "sync"}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>

              <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  { icon: Cpu, label: "LLM" },
                  { icon: Workflow, label: "Flows" },
                  { icon: MessageSquare, label: "Inbox" },
                  { icon: Bot, label: "Agents" },
                ].map(({ icon: Icon, label }) => (
                  <div
                    key={label}
                    className="flex flex-col items-center gap-2 rounded-xl border border-[#1f2430] bg-black/20 px-2 py-3 text-center"
                  >
                    <Icon className="h-4 w-4 text-purple-400" />
                    <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
                      {label}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="border-y border-[#1f2430]/80 bg-[#0a0b10]/50">
          <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                {
                  icon: GitBranch,
                  title: "Flow Builder",
                  text: "Визуальные сценарии с LLM, условиями, CRM и SQL-узлами.",
                },
                {
                  icon: Radio,
                  title: "Омниканальность",
                  text: "WhatsApp, Telegram и operator inbox в одной консоли.",
                },
                {
                  icon: Sparkles,
                  title: "LLM Gateway",
                  text: "Маршрутизация моделей, кэш промптов и учёт токенов.",
                },
                {
                  icon: Bot,
                  title: "AI Agents",
                  text: "Профили агентов, RAG, публикация flow и health telemetry.",
                },
              ].map((item) => (
                <article
                  key={item.title}
                  className="rounded-2xl border border-[#1f2430] bg-[#0e1017] p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-purple-500/30"
                >
                  <item.icon className="h-5 w-5 text-cyan-400" />
                  <h3 className="mt-3 text-sm font-semibold text-white">{item.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-zinc-500">{item.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-purple-300/80">
                Changelog
              </p>
              <h2 className="mt-2 text-2xl font-bold text-white sm:text-3xl">
                Обновления и roadmap
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-zinc-500">
                Прозрачный журнал релизов MP.AI: что уже в production и что команда выкатывает
                дальше.
              </p>
            </div>
          </div>

          <div className="mt-8">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-emerald-400/90">
              Выполненные релизы
            </h3>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {CHANGELOG_RELEASED.map((entry) => (
                <ChangelogCard key={entry.id} entry={entry} />
              ))}
            </div>
          </div>

          <div className="mt-10">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-cyan-400/90">
              В разработке
            </h3>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {CHANGELOG_IN_PROGRESS.map((entry) => (
                <ChangelogCard key={entry.id} entry={entry} />
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
          <div className="relative overflow-hidden rounded-3xl border border-purple-500/20 bg-gradient-to-br from-[#0e1017] via-[#10131c] to-[#0a0c14] p-8 sm:p-10">
            <div
              aria-hidden
              className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-purple-500/20 blur-3xl"
            />
            <div className="relative">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-cyan-400">
                Ready to deploy
              </p>
              <h2 className="mt-3 text-2xl font-bold text-white sm:text-3xl">
                Запустите своего AI-агента за один вечер
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-relaxed text-zinc-400 sm:text-base">
                Создайте workspace, подключите канал, соберите сценарий в Flow Builder и ведите
                сделки в Native CRM — всё в одной платформе MP.AI.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                {isAuthenticated ? (
                  <Link
                    href="/dashboard"
                    className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-semibold text-black transition-all duration-300 hover:bg-zinc-200"
                  >
                    Открыть платформу
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                ) : (
                  <>
                    <Link
                      href="/register"
                      className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-semibold text-black transition-all duration-300 hover:bg-zinc-200"
                    >
                      Создать аккаунт
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                    <Link
                      href="/login"
                      className="inline-flex items-center gap-2 rounded-xl border border-[#1f2430] px-5 py-3 text-sm font-medium text-zinc-200 transition-all duration-300 hover:border-purple-500/40"
                    >
                      Войти
                    </Link>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-[#1f2430]/80 py-6 text-center text-xs text-zinc-600">
        MP.AI Gateway · Production AI Platform · {new Date().getFullYear()}
      </footer>
    </div>
  );
}
