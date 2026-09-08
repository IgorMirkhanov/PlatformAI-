"""Ensure CHROMA_AUTH_TOKEN exists in env files. Never prints the token."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

TOKEN_NAME = "CHROMA_AUTH_TOKEN"
PROVIDER_NAME = "CHROMA_AUTHN_PROVIDER"
PROVIDER_VALUE = "chromadb.auth.token_authn.TokenAuthenticationServerProvider"


def upsert(path: Path, updates: dict[str, str]) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    changed: list[str] = []
    for line in lines:
        stripped = line.strip()
        replaced = False
        for name, value in updates.items():
            if stripped.startswith(f"{name}=") or stripped.startswith(f"{name} ="):
                if name not in seen:
                    current = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                    if current and current != "replace-with-openssl-rand-hex-32":
                        out.append(line)
                    else:
                        out.append(f"{name}={value}")
                        changed.append(name)
                    seen.add(name)
                replaced = True
                break
        if not replaced:
            out.append(line)
    for name, value in updates.items():
        if name not in seen:
            out.append(f"{name}={value}")
            changed.append(name)
    if changed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def existing_token(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(f"{TOKEN_NAME}="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value and value != "replace-with-openssl-rand-hex-32":
                return value
    return None


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    files = [root / ".env.production", root / ".env"]
    token = next((existing_token(path) for path in files if existing_token(path)), None)
    if not token:
        token = secrets.token_hex(32)
    for path in files:
        changed = upsert(path, {TOKEN_NAME: token, PROVIDER_NAME: PROVIDER_VALUE})
        print(f"{path.name}: {'updated ' + ','.join(changed) if changed else 'unchanged'}")


if __name__ == "__main__":
    main()
