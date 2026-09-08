"""Print fingerprints of encryption keys in env files. Never prints key material."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            values[name] = value
    return values


def fingerprint(value: str | None) -> str:
    if not value:
        return "unset"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def describe_material(value: str | None) -> str:
    if not value:
        return "missing"
    raw = value.encode("utf-8")
    if len(raw) == 32:
        return "32-byte-utf8"
    if len(value) == 44:
        return "likely-b64-32"
    if len(value) == 64:
        return "likely-hex-32"
    return f"len={len(value)} (sha256-fallback)"


def report(label: str, path: Path) -> None:
    if not path.exists():
        print(f"{label}: missing")
        return
    env = parse_env(path)
    cred = env.get("CREDENTIALS_ENCRYPTION_KEY")
    enc = env.get("ENCRYPTION_KEY")
    old = env.get("CREDENTIALS_ENCRYPTION_KEYS_OLD") or ""
    retired = [part.strip() for part in old.split(",") if part.strip()]
    print(f"{label}:")
    print(f"  CREDENTIALS_ENCRYPTION_KEY fp={fingerprint(cred)} shape={describe_material(cred)}")
    print(f"  ENCRYPTION_KEY             fp={fingerprint(enc)} shape={describe_material(enc)}")
    print(f"  same_active_pair           {fingerprint(cred) == fingerprint(enc)}")
    print(f"  retired_count              {len(retired)}")
    for index, item in enumerate(retired, start=1):
        print(f"  retired[{index}]               fp={fingerprint(item)} shape={describe_material(item)}")
    print(f"  CREDENTIALS_KEY_VERSION    {env.get('CREDENTIALS_KEY_VERSION') or 'unset'}")
    kms_raw = env.get("KMS_KEYS") or ""
    print(f"  KMS_KEYS_set               {bool(kms_raw)}")
    if kms_raw:
        import json

        try:
            parsed = json.loads(kms_raw)
            for version, secret in parsed.items():
                print(
                    f"  KMS_KEYS[{version}]            fp={fingerprint(str(secret))} "
                    f"shape={describe_material(str(secret))}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  KMS_KEYS_parse_error        {type(exc).__name__}")


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    report(".env.production", root / ".env.production")
    report(".env", root / ".env")
    backups = sorted(root.glob(".env.production.bak-*"))
    if not backups:
        print("backups: none")
        return
    for backup in backups[-3:]:
        report(backup.name, backup)


if __name__ == "__main__":
    main()
