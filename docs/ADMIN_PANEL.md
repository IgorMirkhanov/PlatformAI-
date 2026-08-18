# Admin Panel & Impersonation (MP.AI)

Full-scale platform Admin Panel for SUPERADMIN / SUPPORT staff.

## Routes

| Surface | Path |
|---------|------|
| Admin UI | `/admin`, `/admin/users`, `/admin/bots`, `/admin/billing`, `/admin/audit`, `/admin/impersonate`, `/admin/logs` |
| Legacy redirects | `/dashboard/admin/*` → `/admin` |
| API prefix | `/api/v1/admin/*` |

## Backend layout

```
backend/app/
├── api/dependencies/{admin.py,auth.py}
├── api/endpoints/admin/
│   ├── dashboard.py
│   ├── users.py
│   ├── bots.py
│   ├── billing.py
│   ├── audit.py
│   └── impersonate.py
├── core/middleware/impersonation.py
├── schemas/admin.py
├── services/audit_service.py
└── models/audit_log.py   # alias → AdminAuditLog
```

## Impersonation flow

1. Staff opens **Users** (or **Impersonate**) and clicks **Login as**.
2. Frontend calls `POST /api/v1/admin/impersonate` with `{ "email": "..." }`  
   (or `POST /api/v1/admin/impersonate/user/{user_id}`).
3. Backend checks `SUPERADMIN` / `SUPPORT`, refuses SUPERADMIN/SUPPORT targets, writes `impersonation_start` to `admin_audit_logs`, and mints a JWT:
   - `sub` = target user id  
   - `typ` = `impersonation`  
   - `impersonated_by` = admin id  
   - TTL = **1 hour**
4. Frontend stores the original admin token + meta (`original_admin_token`, `impersonation_meta`), sets the new Bearer, redirects to `/dashboard`.
5. **ImpersonationBar** (red) stays visible for the whole session.
6. Exit restores the admin token, calls `POST /api/v1/admin/impersonate/end`, redirects to `/admin`.

### Curl example

```bash
# Start (as SUPERADMIN access token)
curl -X POST "$API/api/v1/admin/impersonate" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"email":"client@acme.com"}'

# End (while still holding the impersonation Bearer)
curl -X POST "$API/api/v1/admin/impersonate/end" \
  -H "Authorization: Bearer $IMPERSONATION_JWT" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Security controls

| Control | Implementation |
|---------|----------------|
| Role gate | `get_current_admin()` / `get_current_superadmin` |
| No SUPERADMIN/SUPPORT target | `assert_impersonation_allowed` |
| Critical writes blocked while impersonating | `ensure_not_impersonated` on billing subscribe/top-up/deposit, Stripe checkout/portal, admin balance adjust |
| Rate limit | `10/minute` on impersonate endpoints (SlowAPI) |
| Token TTL | 1 hour (`create_impersonation_token`) |
| Audit | every start/end + balance adjust |
| Request flags | `ImpersonationMiddleware` sets `request.state.is_impersonating` |

## Migration

```bash
cd backend
alembic upgrade head   # includes 022_user_is_support
```

Promote support staff:

```sql
UPDATE users SET is_support = true WHERE email = 'support@mp.ai';
```

## Frontend components

- `components/admin/AdminSidebar.tsx`
- `components/admin/AdminDataTable.tsx`
- `components/admin/StatCard.tsx`
- `components/auth/ImpersonationBar.tsx` (alias of red `ImpersonationBanner`)
- `lib/hooks/useImpersonation.ts`
- `lib/auth/admin.ts`

## Next steps

1. Wire SUPPORT role into FE gate (`is_support` on `/team/me`).
2. Optional: step-up **MFA** before impersonation (password re-auth is already required).
3. Optional: install `@tanstack/react-table` and swap `AdminDataTable` internals.
4. SIEM export of `admin_audit_logs`.
5. ~~Session revocation list for stolen impersonation JWTs~~ — done (`impersonation:revoked:{jti}` in Redis; `/impersonate/end` denylists immediately).
