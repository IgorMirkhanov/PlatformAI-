"""Copy crypto-related keys from .env.production to .env without printing values."""

from __future__ import annotations

import sys
from pathlib import Path

NAMES = (
    "CREDENTIALS_ENCRYPTION_KEY",
    "ENCRYPTION_KEY",
    "CREDENTIALS_ENCRYPTION_KEYS_OLD",
    "KMS_KEYS",
    "CREDENTIALS_KEY_VERSION",
    "CHROMA_AUTH_TOKEN",
    "CHROMA_AUTHN_PROVIDER",
)


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        name, _, value = raw.partition("=")
        values[name.strip()] = value.strip()
    return values


def upsert(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        replaced = False
        for name, value in updates.items():
            if stripped.startswith(f"{name}=") or stripped.startswith(f"{name} ="):
                if name not in seen:
                    out.append(f"{name}={value}")
                    seen.add(name)
                replaced = True
                break
        if not replaced:
            out.append(line)
    for name, value in updates.items():
        if name not in seen:
            out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    source = parse(root / ".env.production")
    updates = {name: source[name] for name in NAMES if name in source}
    upsert(root / ".env", updates)
    print(f"synced {len(updates)} crypto/chroma keys -> .env")


if __name__ == "__main__":
    main()
