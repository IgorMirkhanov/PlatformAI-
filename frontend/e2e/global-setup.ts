import { writeE2EAuthStorageState } from "./helpers/session";

/**
 * Writes `playwright/.auth/user.json` so tests receive a JWT cookie with `exp`
 * before the first navigation (Next.js middleware gate).
 */
export default async function globalSetup(): Promise<void> {
  const origin = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";
  writeE2EAuthStorageState("playwright/.auth/user.json", origin);
}
