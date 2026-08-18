"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Clock3,
  Copy,
  Loader2,
  Mail,
  Shield,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";

import { SettingsSectionNav } from "@/components/settings/SettingsSectionNav";
import { QuotaProgressBar } from "@/components/dashboard/QuotaProgressBar";
import {
  createInvite,
  getOrganizationInvites,
  getOrganizationMembers,
  revokeInvite,
  type OrgInvite,
  type OrgInviteRole,
} from "@/lib/billing/api";
import { canManageTeam } from "@/lib/permissions";
import { useOrganizationStore } from "@/lib/stores/use-organization-store";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";
import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";
import {
  ADMIN_INVITE_ROLE_OPTIONS,
  INVITE_ROLE_OPTIONS,
  ROLE_BADGE_STYLES,
  ROLE_LABELS,
  type TeamMember,
  type UserRole,
} from "@/types/team";
import { revokeTeamMember, updateTeamMemberRole } from "@/lib/api";

function displayRoleLabel(role: string): string {
  return ROLE_LABELS[role as UserRole] ?? role;
}

function formatJoined(iso: string): string {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return iso.slice(0, 10);
  }
}

function buildInviteLink(token: string): string {
  const params = new URLSearchParams({ token });
  if (typeof window === "undefined") {
    return `/dashboard/settings/team?accept=${params.get("token")}`;
  }
  return `${window.location.origin}/dashboard/settings/team?token=${encodeURIComponent(token)}`;
}

export default function DashboardTeamSettingsPage() {
  const currentUser = useBotStore((state) => state.currentUser);
  const loadCurrentUser = useBotStore((state) => state.loadCurrentUser);
  const usage = useOrganizationStore((s) => s.usage);
  const loadUsage = useOrganizationStore((s) => s.loadUsage);
  const { showToast } = useToast();

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [invites, setInvites] = useState<OrgInvite[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<OrgInviteRole>("MEMBER");
  const [lastInviteToken, setLastInviteToken] = useState<string | null>(null);
  const [lastInviteLink, setLastInviteLink] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyMemberId, setBusyMemberId] = useState<string | null>(null);
  const [busyInviteId, setBusyInviteId] = useState<string | null>(null);

  const canManage = canManageTeam(currentUser?.role);
  const inviteRoleOptions =
    currentUser?.role === "OWNER" ? INVITE_ROLE_OPTIONS : ADMIN_INVITE_ROLE_OPTIONS;

  const loadTeam = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const [membersResponse, invitesResponse] = await Promise.all([
        getOrganizationMembers(),
        canManage ? getOrganizationInvites() : Promise.resolve({ items: [], total: 0 }),
      ]);
      setMembers(membersResponse.members);
      setInvites(invitesResponse.items);
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось загрузить команду."), "error");
    } finally {
      setLoading(false);
    }
  }, [canManage, showToast]);

  useEffect(() => {
    void loadCurrentUser();
    void loadUsage();
  }, [loadCurrentUser, loadUsage]);

  useEffect(() => {
    void loadTeam();
  }, [loadTeam]);

  const sortedMembers = useMemo(
    () =>
      [...members].sort((left, right) => {
        const order: UserRole[] = ["OWNER", "ADMIN", "MEMBER", "PROMPT_ENGINEER", "OPERATOR"];
        return order.indexOf(left.role) - order.indexOf(right.role);
      }),
    [members],
  );

  const handleInvite = async (): Promise<void> => {
    if (!inviteEmail.trim()) {
      showToast("Введите email.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const response = await createInvite(inviteEmail.trim(), inviteRole);
      const link = buildInviteLink(response.token);
      setLastInviteToken(response.token);
      setLastInviteLink(link);
      try {
        await navigator.clipboard.writeText(link);
        showToast("Приглашение создано. Ссылка скопирована.", "success");
      } catch {
        showToast("Приглашение создано. Скопируйте ссылку ниже.", "success");
      }
      setInviteEmail("");
      setInviteOpen(false);
      await loadTeam();
      await loadUsage();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось отправить приглашение."), "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRoleChange = async (member: TeamMember, next: UserRole): Promise<void> => {
    if (next === "OWNER") return;
    setBusyMemberId(member.id);
    try {
      await updateTeamMemberRole(member.id, { role: next });
      showToast(`Роль обновлена для ${member.email}.`, "success");
      await loadTeam();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось обновить роль."), "error");
    } finally {
      setBusyMemberId(null);
    }
  };

  const handleRevoke = async (member: TeamMember): Promise<void> => {
    setBusyMemberId(member.id);
    try {
      await revokeTeamMember(member.id);
      showToast(`Доступ отозван для ${member.email}.`, "success");
      await loadTeam();
      await loadUsage();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось отозвать доступ."), "error");
    } finally {
      setBusyMemberId(null);
    }
  };

  const handleCancelInvite = async (invite: OrgInvite): Promise<void> => {
    setBusyInviteId(invite.id);
    try {
      await revokeInvite(invite.id);
      showToast("Приглашение отозвано.", "success");
      await loadTeam();
    } catch (error) {
      showToast(getApiErrorMessage(error, "Не удалось отозвать приглашение."), "error");
    } finally {
      setBusyInviteId(null);
    }
  };

  const quotaMetrics = usage
    ? [
        {
          label: "Active Bots",
          used: usage.active_bots,
          limit: usage.active_bots_limit,
        },
        {
          label: "Team Slots",
          used: usage.team_slots_used,
          limit: usage.team_slots_limit,
        },
      ]
    : [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 lg:px-8">
      <SettingsSectionNav role={currentUser?.role} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300/70">
            Настройки организации
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-zinc-50">Команда</h1>
          <p className="mt-2 text-sm text-zinc-500">
            Участники и email-приглашения для активного workspace.
          </p>
        </div>
        {canManage ? (
          <button
            type="button"
            onClick={() => setInviteOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:from-violet-500 hover:to-indigo-500"
          >
            <UserPlus className="h-4 w-4" />
            Пригласить
          </button>
        ) : null}
      </header>

      {quotaMetrics.length > 0 ? <QuotaProgressBar metrics={quotaMetrics} /> : null}

      {lastInviteLink ? (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-100">
          <p className="font-medium">Ссылка приглашения (показывается один раз)</p>
          <p className="mt-1 break-all text-xs text-emerald-200/90">{lastInviteLink}</p>
          {lastInviteToken ? (
            <p className="mt-2 break-all font-mono text-[11px] text-emerald-300/80">
              token: {lastInviteToken}
            </p>
          ) : null}
          <button
            type="button"
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-emerald-300 underline"
            onClick={() => {
              void navigator.clipboard.writeText(lastInviteLink);
              showToast("Ссылка скопирована.", "success");
            }}
          >
            <Copy className="h-3 w-3" />
            Копировать снова
          </button>
        </div>
      ) : null}

      {!canManage ? (
        <div className="rounded-2xl border border-zinc-800/80 bg-zinc-950/50 px-4 py-3 text-sm text-zinc-400">
          <span className="inline-flex items-center gap-2">
            <Shield className="h-4 w-4 text-zinc-500" />
            Только просмотр — приглашать и менять роли могут OWNER и ADMIN.
          </span>
        </div>
      ) : null}

      <section className="rounded-2xl border border-zinc-800/80 bg-[#0d0d0f]/90 p-5">
        <div className="mb-5 flex items-center gap-3">
          <Users className="h-5 w-5 text-violet-400" />
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Участники</h2>
            <p className="text-xs text-zinc-500">{sortedMembers.length} в workspace</p>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[160px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-zinc-800/80">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-zinc-950/80 text-[11px] uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Участник</th>
                  <th className="px-4 py-3 font-medium">Роль</th>
                  <th className="px-4 py-3 font-medium">Добавлен</th>
                  <th className="px-4 py-3 font-medium">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/80">
                {sortedMembers.map((member) => {
                  const isSelf = member.id === currentUser?.id;
                  const isOwner = member.role === "OWNER";
                  return (
                    <tr key={member.id} className="bg-zinc-950/30">
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-100">{member.full_name || "—"}</div>
                        <div className="text-xs text-zinc-500">{member.email}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1",
                            ROLE_BADGE_STYLES[member.role],
                          )}
                        >
                          {displayRoleLabel(member.role)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-zinc-400">{formatJoined(member.created_at)}</td>
                      <td className="px-4 py-3">
                        {canManage && !isOwner && !isSelf ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <select
                              value={member.role}
                              disabled={busyMemberId === member.id}
                              onChange={(e) =>
                                void handleRoleChange(member, e.target.value as UserRole)
                              }
                              className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
                            >
                              {inviteRoleOptions.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              disabled={busyMemberId === member.id}
                              onClick={() => void handleRevoke(member)}
                              className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                            >
                              {busyMemberId === member.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="h-3 w-3" />
                              )}
                              Удалить
                            </button>
                          </div>
                        ) : (
                          <span className="text-xs text-zinc-600">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-zinc-800/80 bg-[#0d0d0f]/90 p-5">
        <div className="mb-5 flex items-center gap-3">
          <Mail className="h-5 w-5 text-amber-300" />
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Активные приглашения</h2>
            <p className="text-xs text-zinc-500">{invites.length} ожидают принятия</p>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[100px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
          </div>
        ) : invites.length === 0 ? (
          <p className="text-sm text-zinc-500">Нет активных приглашений.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-zinc-800/80">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-zinc-950/80 text-[11px] uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Роль</th>
                  <th className="px-4 py-3 font-medium">Истекает</th>
                  <th className="px-4 py-3 font-medium">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/80">
                {invites.map((invite) => (
                  <tr key={invite.id}>
                    <td className="px-4 py-3 text-zinc-100">{invite.email}</td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1",
                          ROLE_BADGE_STYLES[(invite.role as UserRole) ?? "OPERATOR"] ??
                            ROLE_BADGE_STYLES.OPERATOR,
                        )}
                      >
                        {displayRoleLabel(invite.role)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-zinc-400">
                      <span className="inline-flex items-center gap-1.5">
                        <Clock3 className="h-3.5 w-3.5" />
                        {formatJoined(invite.expires_at)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {canManage ? (
                        <button
                          type="button"
                          disabled={busyInviteId === invite.id}
                          onClick={() => void handleCancelInvite(invite)}
                          className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900 disabled:opacity-50"
                        >
                          {busyInviteId === invite.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Trash2 className="h-3 w-3" />
                          )}
                          Отозвать
                        </button>
                      ) : (
                        <span className="text-xs text-zinc-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="text-xs text-zinc-600">
        Биллинг и кошелёк:{" "}
        <Link href="/dashboard/settings/billing" className="text-violet-400 hover:text-violet-300">
          открыть раздел
        </Link>
      </p>

      {inviteOpen ? (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm"
          onClick={() => !submitting && setInviteOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-zinc-800 bg-[#0d0d0f] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-zinc-50">Пригласить участника</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  После создания появится ссылка и сырой токен — скопируйте их один раз.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setInviteOpen(false)}
                className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-900"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-5 space-y-3">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-zinc-400">Email</span>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm outline-none focus:border-zinc-600"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-zinc-400">Роль</span>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as OrgInviteRole)}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2.5 text-sm outline-none focus:border-zinc-600"
                >
                  {inviteRoleOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setInviteOpen(false)}
                disabled={submitting}
                className="rounded-xl border border-zinc-800 px-4 py-2 text-sm text-zinc-300"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => void handleInvite()}
                disabled={submitting}
                className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                Создать приглашение
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
