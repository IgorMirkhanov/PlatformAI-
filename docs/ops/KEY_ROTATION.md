# Rotating the credential encryption key

Every secret the platform stores at rest — Telegram/WhatsApp channel tokens, CRM
OAuth tokens, BYOK LLM API keys, SQL connection strings — is sealed with key
material derived from `CREDENTIALS_ENCRYPTION_KEY`. Replacing that value without
following this procedure makes every one of those rows permanently unreadable.

## The one rule

**Never remove the old key in the same step that installs the new one.** Reads
must keep working while rows are migrated. `CREDENTIALS_ENCRYPTION_KEYS_OLD`
exists precisely for that overlap window.

## Which codec covers what

The platform has two at-rest schemes, and a rotation has to satisfy both:

| Scheme | Storage | Rotation mechanism |
|---|---|---|
| `app.core.crypto` (`aesgcm:` payloads) | `bot_channels.encrypted_token`, `bots.credentials` JSONB, `integration_connections.encrypted_*`, `db_connections.connection_string_encrypted` | `CREDENTIALS_ENCRYPTION_KEYS_OLD` (comma-separated, read-only) |
| `app.services.crypto_service` (versioned KEK envelope) | `credentials.encrypted_payload`, `integration_oauth_apps.encrypted_client_secret` | `KMS_KEYS` version map + `CREDENTIALS_KEY_VERSION` |

BYOK LLM keys in `organization_api_keys.encrypted_api_key` use a Fernet variant
of the first scheme and honour the same retired-key list.

`resolve_retired_key_materials()` also treats every `KMS_KEYS` value other than
the active key as a retired decrypt key. A vault-only rotation that forgot
`CREDENTIALS_ENCRYPTION_KEYS_OLD` used to leave Telegram tokens unreadable even
though the old KEK was still in `KMS_KEYS`. Still populate the OLD list so the
overlap is obvious in the env file.

## Procedure

`rotate-encryption-key.ps1` performs steps 1–2 for both schemes at once.

1. **Generate a real 32-byte key.** `openssl rand -base64 32` (44 base64
   characters). Anything that does not decode to exactly 32 bytes falls back to
   an SHA-256 derivation and logs `Crypto.key_derived_via_sha256` — it works, but
   it is not what you want in production.
2. **Install it, retiring the current key.** In *both* env files (see the
   precedence warning below):

   ```bash
   CREDENTIALS_ENCRYPTION_KEY=<new>
   ENCRYPTION_KEY=<new>
   CREDENTIALS_ENCRYPTION_KEYS_OLD=<previous>
   KMS_KEYS={"1":"<previous>","2":"<new>"}
   CREDENTIALS_KEY_VERSION=2
   ```

3. **Restart the app tier** and confirm the startup line reports the key you
   expect:

   ```
   Crypto.startup_ok | algorithm=AES-256-GCM production=True retired_keys=1 key_fingerprint=<8 hex> environment=production
   Crypto.rotation_pending | 1 retired key(s) still needed for reads
   ```

4. **Migrate the rows:**

   ```bash
   python scripts/reencrypt_credentials.py --dry-run   # inventory first
   python scripts/reencrypt_credentials.py
   ```

   Re-run until every table reports `rewritten=0` with `unrecoverable=0`.

5. **Drop the retired key** from `CREDENTIALS_ENCRYPTION_KEYS_OLD` (and stale
   `KMS_KEYS` versions), restart, and verify with
   `scripts/audit_channel_credentials.py` that channels still report `OK`.
   `Crypto.rotation_pending` must be gone.

6. **Delete the `.bak-*` env files** the rotation script created — they contain
   the retired key.

## Rows reported `unrecoverable`

Sealed with key material nobody holds any more. They cannot be recovered by any
means; the credential has to be re-entered through the UI.
`reencrypt_credentials.py --purge-unrecoverable` clears such channel tokens and
flips the channel to disconnected, so the UI stops advertising a dead channel as
connected and prompts for the credential instead.

## Warning: `environment:` overrides `env_file:`

`docker-compose.prod.yml` sets crypto variables as
`CREDENTIALS_ENCRYPTION_KEY: ${CREDENTIALS_ENCRYPTION_KEY:-}`. Compose resolves
`${...}` from **the invoking shell or `.env`**, not from
`env_file: [.env.production]`, and `environment:` wins over `env_file`. Two
consequences:

- Keep the crypto trio in sync in **both** `.env` and `.env.production`.
- A stray `CREDENTIALS_ENCRYPTION_KEY` or `ENVIRONMENT` exported in the shell
  that runs `docker compose up` silently replaces the production value — for
  example a terminal previously used to run the test suite. Always start a clean
  shell for deploys, and check `key_fingerprint` / `environment` in the startup
  log afterwards.
