export type UserRole = "OWNER" | "ADMIN" | "MEMBER" | "PROMPT_ENGINEER" | "OPERATOR";

export type TeamInvitationStatus = "PENDING" | "ACCEPTED" | "EXPIRED";

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  company_name: string;
  company_id: string;
  role: UserRole;
  timezone: string;
  is_superadmin?: boolean;
  is_support?: boolean;
  created_at: string;
}

export interface CompanyWorkspace {
  id: string;
  name: string;
  role: UserRole;
  timezone: string;
  is_active: boolean;
}

export interface OrganizationsListResponse {
  active_company_id: string;
  organizations: CompanyWorkspace[];
}

export interface CreateCompanyRequest {
  name: string;
}

export interface CreateCompanyResponse {
  company: CompanyWorkspace;
  access_token?: string | null;
  message: string;
}

export interface SwitchCompanyRequest {
  company_id: string;
}

export interface SwitchCompanyResponse {
  company_id: string;
  company_name: string;
  role: UserRole;
  timezone: string;
  access_token?: string | null;
  message: string;
}

export interface UpdateCurrentUserRequest {
  company_name?: string;
  full_name?: string;
  timezone?: string;
}

export interface TeamMember {
  id: string;
  email: string;
  full_name: string;
  company_name: string;
  company_id: string;
  role: UserRole;
  created_at: string;
}

export interface TeamInvitation {
  id: string;
  company_id: string;
  email: string;
  role: UserRole;
  expires_at: string;
  status: TeamInvitationStatus;
  created_at: string;
}

export interface TeamMembersResponse {
  company_id: string;
  members: TeamMember[];
  pending_invitations: TeamInvitation[];
  total_members: number;
  total_pending: number;
}

export interface TeamInviteRequest {
  email: string;
  role: Exclude<UserRole, "OWNER">;
}

export interface TeamInviteResponse {
  invitation_id: string;
  email: string;
  role: UserRole;
  token: string;
  expires_at: string;
  message: string;
}

export interface AcceptTeamInviteRequest {
  token: string;
  email: string;
  password: string;
  full_name?: string;
}

export interface UpdateTeamMemberRoleRequest {
  role: UserRole;
}

export const ROLE_LABELS: Record<UserRole, string> = {
  OWNER: "Владелец",
  ADMIN: "Администратор",
  MEMBER: "Участник",
  PROMPT_ENGINEER: "Prompt-инженер",
  OPERATOR: "Оператор",
};

export const INVITE_ROLE_OPTIONS: Array<{
  value: Exclude<UserRole, "OWNER">;
  label: string;
}> = [
  { value: "ADMIN", label: "Администратор" },
  { value: "MEMBER", label: "Участник" },
  { value: "OPERATOR", label: "Оператор" },
  { value: "PROMPT_ENGINEER", label: "Prompt-инженер" },
];

/** Roles an ADMIN actor may assign when inviting (OWNER may invite ADMIN too). */
export const ADMIN_INVITE_ROLE_OPTIONS: Array<{
  value: Exclude<UserRole, "OWNER" | "ADMIN">;
  label: string;
}> = [
  { value: "MEMBER", label: "Участник" },
  { value: "OPERATOR", label: "Оператор" },
  { value: "PROMPT_ENGINEER", label: "Prompt-инженер" },
];

export const ROLE_BADGE_STYLES: Record<UserRole, string> = {
  OWNER: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  ADMIN: "bg-indigo-500/15 text-indigo-300 ring-indigo-500/30",
  MEMBER: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  PROMPT_ENGINEER: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  OPERATOR: "bg-zinc-700/40 text-zinc-300 ring-zinc-600/40",
};
