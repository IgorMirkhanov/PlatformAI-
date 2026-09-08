"""Migrate every at-rest secret onto the currently active encryption key.

Run this after rotating ``CREDENTIALS_ENCRYPTION_KEY`` while the previous key is
still listed in ``CREDENTIALS_ENCRYPTION_KEYS_OLD`` (and, for the versioned
vault, still present in ``KMS_KEYS``). Rows that already decrypt with the active
key are left untouched, so the script is idempotent and safe to re-run.

    python scripts/reencrypt_credentials.py --dry-run   # report only
    python scripts/reencrypt_credentials.py             # rewrite rows

Once it reports 0 rows on retired keys, drop the retired entries from the env.

Rows reported as ``unrecoverable`` were sealed with a key nobody holds any more.
They can never be read, and a channel left holding one keeps advertising itself
as connected while silently failing to deliver. ``--purge-unrecoverable`` clears
those ciphertexts and flips the owning channel to disconnected so the UI asks for
the credential again.

Prints table/column names, row ids and counts only — never secret material.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import (
    AESGCM_PREFIX,
    FieldEncryptor,
    resolve_encryption_key_material,
    resolve_retired_key_materials,
)
from app.db.session import async_session_factory

# Only aesgcm: payloads are key-derived. Legacy enc:/plain: rows are left alone —
# FieldEncryptor passes them through, so "re-sealing" them would be a no-op lie.
SEALED_PREFIXES = (AESGCM_PREFIX,)


class Stats:
    def __init__(self) -> None:
        self.scanned = 0
        self.rewritten = 0
        self.already_active = 0
        self.unrecoverable = 0

    def line(self, label: str) -> str:
        return (
            f"{label}: scanned={self.scanned} rewritten={self.rewritten} "
            f"already_active={self.already_active} unrecoverable={self.unrecoverable}"
        )


def _active_only_encryptor() -> FieldEncryptor:
    """Decrypts with the active key alone — used to detect rows needing no work."""
    return FieldEncryptor(
        resolve_encryption_key_material(), require_key=True, retired_key_materials=[]
    )


def _rotation_encryptor() -> FieldEncryptor:
    """Decrypts with the active key, then any retired key."""
    return FieldEncryptor(
        resolve_encryption_key_material(),
        require_key=True,
        retired_key_materials=resolve_retired_key_materials(),
    )


def _looks_sealed(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SEALED_PREFIXES)


def _reseal(value: str, stats: Stats) -> str | None:
    """Return a re-sealed value, or None when no rewrite is needed/possible."""
    stats.scanned += 1

    try:
        _active_only_encryptor().decrypt(value)
        stats.already_active += 1
        return None
    except Exception:
        pass

    try:
        plaintext = _rotation_encryptor().decrypt(value)
    except Exception:
        stats.unrecoverable += 1
        return None

    stats.rewritten += 1
    return _active_only_encryptor().encrypt(plaintext)


def _walk_json(node: Any, stats: Stats) -> tuple[Any, bool]:
    """Recursively re-seal sealed strings inside a JSON structure."""
    if isinstance(node, dict):
        changed = False
        out = {}
        for key, value in node.items():
            out[key], sub_changed = _walk_json(value, stats)
            changed = changed or sub_changed
        return out, changed

    if isinstance(node, list):
        changed = False
        out_list = []
        for item in node:
            new_item, sub_changed = _walk_json(item, stats)
            out_list.append(new_item)
            changed = changed or sub_changed
        return out_list, changed

    if _looks_sealed(node):
        resealed = _reseal(node, stats)
        if resealed is not None:
            return resealed, True

    return node, False


async def _migrate_text_column(
    db: AsyncSession, table: str, column: str, *, dry_run: bool
) -> Stats:
    stats = Stats()
    rows = (
        await db.execute(
            text(f"SELECT id, {column} AS value FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
        )
    ).all()

    for row in rows:
        if not _looks_sealed(row.value):
            continue
        resealed = _reseal(row.value, stats)
        if resealed is None or dry_run:
            continue
        await db.execute(
            text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),  # noqa: S608
            {"value": resealed, "id": row.id},
        )

    return stats


async def _migrate_json_column(
    db: AsyncSession, table: str, column: str, *, dry_run: bool
) -> Stats:
    import json

    stats = Stats()
    rows = (
        await db.execute(
            text(f"SELECT id, {column} AS value FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
        )
    ).all()

    for row in rows:
        payload = row.value
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        migrated, changed = _walk_json(payload, stats)
        if not changed or dry_run:
            continue
        await db.execute(
            text(f"UPDATE {table} SET {column} = CAST(:value AS jsonb) WHERE id = :id"),  # noqa: S608
            {"value": json.dumps(migrated, ensure_ascii=False), "id": row.id},
        )

    return stats


async def _migrate_fernet_api_keys(db: AsyncSession, *, dry_run: bool) -> Stats:
    """organization_api_keys.encrypted_api_key uses the Fernet codec (BYOK LLM keys)."""
    from app.services.ai_keys_service import decrypt_api_key, encrypt_api_key

    stats = Stats()
    rows = (
        await db.execute(
            text(
                "SELECT id, encrypted_api_key AS value FROM organization_api_keys "
                "WHERE encrypted_api_key IS NOT NULL"
            )
        )
    ).all()

    for row in rows:
        stats.scanned += 1
        try:
            plaintext = decrypt_api_key(row.value)
        except Exception:
            stats.unrecoverable += 1
            continue

        resealed = encrypt_api_key(plaintext)
        # Fernet tokens are non-deterministic, so re-seal unconditionally; the
        # rotation warning in decrypt_api_key is what flags a retired key.
        if dry_run:
            stats.rewritten += 1
            continue
        await db.execute(
            text("UPDATE organization_api_keys SET encrypted_api_key = :value WHERE id = :id"),
            {"value": resealed, "id": row.id},
        )
        stats.rewritten += 1

    return stats


async def _migrate_vault(db: AsyncSession, *, dry_run: bool) -> Stats:
    """credentials.encrypted_payload — versioned KEK envelope (crypto_service)."""
    from app.services.crypto_service import current_key_version, decrypt_payload, encrypt_payload

    stats = Stats()
    version = current_key_version()
    rows = (
        await db.execute(
            text(
                "SELECT id, encrypted_payload, encryption_iv, encryption_tag, key_version "
                "FROM credentials WHERE encrypted_payload IS NOT NULL"
            )
        )
    ).all()

    for row in rows:
        stats.scanned += 1
        if row.key_version == version:
            stats.already_active += 1
            continue
        try:
            payload = decrypt_payload(
                row.encrypted_payload,
                row.encryption_iv,
                row.encryption_tag,
                key_version=int(row.key_version or 1),
            )
        except Exception:
            stats.unrecoverable += 1
            continue

        ciphertext, iv, tag = encrypt_payload(payload)
        stats.rewritten += 1
        if dry_run:
            continue
        await db.execute(
            text(
                "UPDATE credentials SET encrypted_payload = :ct, encryption_iv = :iv, "
                "encryption_tag = :tag, key_version = :kv WHERE id = :id"
            ),
            {"ct": ciphertext, "iv": iv, "tag": tag, "kv": version, "id": row.id},
        )

    return stats


async def _purge_unrecoverable_channels(db: AsyncSession, *, dry_run: bool) -> int:
    """Clear channel tokens that no configured key can read and mark them disconnected."""
    rotation = _rotation_encryptor()
    rows = (
        await db.execute(
            text(
                "SELECT id, encrypted_token FROM bot_channels "
                "WHERE encrypted_token IS NOT NULL"
            )
        )
    ).all()

    orphaned: list[Any] = []
    for row in rows:
        if not _looks_sealed(row.encrypted_token):
            continue
        try:
            rotation.decrypt(row.encrypted_token)
        except Exception:
            orphaned.append(row.id)

    if orphaned and not dry_run:
        await db.execute(
            text(
                "UPDATE bot_channels SET encrypted_token = NULL, status = 'disconnected', "
                "meta_data = COALESCE(meta_data, '{}'::jsonb) "
                "|| '{\"credential_error\": \"decrypt_failed\"}'::jsonb "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": orphaned},
        )

    return len(orphaned)


TEXT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bot_channels", "encrypted_token"),
    ("integration_connections", "encrypted_access_token"),
    ("integration_connections", "encrypted_refresh_token"),
    ("db_connections", "connection_string_encrypted"),
)

JSON_COLUMNS: tuple[tuple[str, str], ...] = (("bots", "credentials"),)

SPECIAL: tuple[tuple[str, Callable[..., Any]], ...] = (
    ("organization_api_keys.encrypted_api_key (fernet)", _migrate_fernet_api_keys),
    ("credentials.encrypted_payload (versioned vault)", _migrate_vault),
)


async def _run_step(db: AsyncSession, label: str, coro_factory) -> Stats | None:
    """Run one migration inside a savepoint.

    A missing table (or any other failure) must only discard that step — without
    the savepoint, the rollback would also throw away every table migrated
    before it in the same transaction.
    """
    savepoint = await db.begin_nested()
    try:
        stats = await coro_factory()
    except Exception as exc:
        await savepoint.rollback()
        print(f"{label}: SKIPPED ({type(exc).__name__})")
        return None
    await savepoint.commit()
    return stats


async def main(dry_run: bool, purge: bool) -> None:
    retired = resolve_retired_key_materials()
    print(f"active_key_configured: {bool(resolve_encryption_key_material())}")
    print(f"retired_keys_available: {len(retired)}")
    print(f"mode: {'DRY-RUN (no writes)' if dry_run else 'REWRITE'}\n")

    async with async_session_factory() as db:
        for table, column in TEXT_COLUMNS:
            label = f"{table}.{column}"
            stats = await _run_step(
                db, label, lambda t=table, c=column: _migrate_text_column(db, t, c, dry_run=dry_run)
            )
            if stats is not None:
                print(stats.line(label))

        for table, column in JSON_COLUMNS:
            label = f"{table}.{column}"
            stats = await _run_step(
                db, label, lambda t=table, c=column: _migrate_json_column(db, t, c, dry_run=dry_run)
            )
            if stats is not None:
                print(stats.line(label))

        for label, handler in SPECIAL:
            stats = await _run_step(db, label, lambda h=handler: h(db, dry_run=dry_run))
            if stats is not None:
                print(stats.line(label))

        if purge:
            count = await _purge_unrecoverable_channels(db, dry_run=dry_run)
            verb = "would clear" if dry_run else "cleared"
            print(f"\npurge_unrecoverable_channels: {verb} {count} channel token(s)")

        if dry_run:
            await db.rollback()
        else:
            await db.commit()

    print(
        "\nUnrecoverable rows hold secrets sealed with a key that is no longer "
        "configured — they must be re-entered through the UI."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    parser.add_argument(
        "--purge-unrecoverable",
        action="store_true",
        dest="purge",
        help="clear channel tokens no configured key can read and mark them disconnected",
    )
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.purge))
