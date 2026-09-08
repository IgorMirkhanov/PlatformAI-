/** Shared support contact — safe for RSC and client imports. */
export const SUPPORT_EMAIL =
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL?.trim() || "support@example.com";

export function supportEmail(): string {
  return SUPPORT_EMAIL;
}
