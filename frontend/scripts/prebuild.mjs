/**
 * Always wipe .next before production builds so dev and build never share a corrupt cache.
 */
import { rmSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function killPort3000() {
  if (process.platform !== "win32") {
    return;
  }
  try {
    execSync(
      'powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"',
      { stdio: "ignore" },
    );
  } catch {
    // Port may already be free.
  }
}

function cleanNextCache() {
  for (const dir of [".next", join("node_modules", ".cache")]) {
    const target = join(root, dir);
    if (existsSync(target)) {
      rmSync(target, { recursive: true, force: true });
    }
  }
}

console.log("[frontend] prebuild: stopping dev on :3000 and clearing .next …");
killPort3000();
cleanNextCache();
console.log("[frontend] prebuild: cache cleared.");
