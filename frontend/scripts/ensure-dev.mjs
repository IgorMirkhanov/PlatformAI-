/**
 * Safe dev startup: free port 3000 and remove production build artifacts from .next
 * (they break CSS/chunk URLs when next dev is still running or restarts after build).
 */
import { existsSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync, spawn } from "node:child_process";

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
    // ignore
  }
}

function cleanIfProductionBuild() {
  const nextDir = join(root, ".next");
  const buildId = join(nextDir, "BUILD_ID");
  const standalone = join(nextDir, "standalone");

  if (!existsSync(nextDir)) {
    return;
  }

  if (existsSync(buildId) || existsSync(standalone)) {
    console.log(
      "[frontend] Detected production .next output — clearing cache before dev (prevents CSS 404) …",
    );
    rmSync(nextDir, { recursive: true, force: true });
    const cache = join(root, "node_modules", ".cache");
    if (existsSync(cache)) {
      rmSync(cache, { recursive: true, force: true });
    }
  }
}

killPort3000();
cleanIfProductionBuild();

const child = spawn("npx", ["next", "dev"], {
  cwd: root,
  stdio: "inherit",
  shell: true,
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
