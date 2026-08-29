# Authentication & Authorization System

## Overview

Podly has a flexible authentication system that can be enabled or disabled based on deployment needs.

## Authentication Modes

### 1. No Authentication (`REQUIRE_AUTH=false`)
- All features accessible without login
- Suitable for personal/single-user instances
- No user management overhead
- RSS feeds accessible by URL only

### 2. With Authentication (`REQUIRE_AUTH=true`)
- Login required for web UI and API
- User role system (admin/user)
- Feed access tokens for podcast players
- Discord SSO support
- Authentik SSO support (single-admin mapping, see below)
- Stripe billing integration

## Components

### AuthSettings (`auth/settings.py`)
Central configuration loaded from environment:

```python
- require_auth: bool
- admin_username: str
- admin_password: str (hashed)
- secret_key: str (session encryption)
```

### User Model

```python
- username: str (normalized lowercase)
- password_hash: str (bcrypt)
- role: str ('admin' or 'user')
- feed_allowance: int (number of feeds allowed)
- discord_id: str (optional SSO)
- manual_feed_allowance: int (admin override)
```

### Roles

**Admin:**
- Full system access
- Manage all feeds and posts
- User management
- Configuration access
- Billing administration

**User:**
- Access whitelisted posts only
- Limited feed allowance
- Personal feed subscriptions

## Session Management

- Flask sessions with server-side storage
- Cookie-based authentication
- Configurable cookie settings:
  - `SESSION_COOKIE_NAME`: Default "podly_session"
  - `SESSION_COOKIE_HTTPONLY`: True (XSS protection)
  - `SESSION_COOKIE_SAMESITE`: Lax (CSRF protection)
  - `SESSION_COOKIE_SECURE`: False (allow HTTP for self-hosting)

## Feed Access Tokens

Since podcast players don't support cookie auth, Podly uses **feed access tokens**:

### Token Structure
```
token_id: 32-char random string
secret: 128-char random string
format in URL: /feed/{token_id}:{secret}/rss
```

### Security Model
- Token stored hashed in database
- Secret acts as password
- Can be revoked by user
- Feed-specific or user-wide access
- Optional expiration (not implemented)

### Usage
```bash
# Generate token (web UI)
# Use in podcast player:
https://podly.example.com/feed/abc123:secret456/rss
```

## Discord SSO

Optional Discord OAuth integration:

**Configuration:**
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_REDIRECT_URI`
- `DISCORD_GUILD_IDS` (restrict to specific servers)

**Flow:**
1. User clicks "Login with Discord"
2. Redirect to Discord OAuth
3. Discord redirects back with code
4. Podly exchanges code for user info
5. Creates/links user account
6. Redirects to app

## Authentik SSO

Optional Authentik OIDC integration, structurally different from Discord SSO:
Discord self-registers a new limited `user`-role account per Discord identity
(`upsert_discord_user_action`); Authentik login always maps to the single
existing local **admin** account instead (`app/auth/authentik_service.py:get_admin_user`).
This is a single-admin-household design, not multi-tenant -- access control
lives in Authentik itself (the OIDC Application's policy binding decides who
can complete the login at all), not in per-identity Podly accounts.

It is a **public OAuth2 client** (PKCE, no `client_secret` stored anywhere)
against Authentik's standard OIDC endpoints, discovered live from
`{issuer}/.well-known/openid-configuration` at boot -- not the Authentik
*proxy outpost* pattern used for other apps behind this household's
Authentik, which would also gate the token-authenticated feed/audio routes
(`/feed/*`, `/api/posts/*/download`, etc.) that podcast clients hit and
cannot complete an interactive SSO redirect for.

**Configuration (env vars only -- no DB-backed settings/admin UI, unlike Discord):**
- `AUTHENTIK_ISSUER` -- e.g. `https://auth.example.com/application/o/<slug>/`
- `AUTHENTIK_CLIENT_ID`
- `AUTHENTIK_REDIRECT_URI` -- `https://<host>/api/auth/authentik/callback`

Enabled only when the discovery fetch succeeds at boot; fails closed (SSO
disabled, not a startup crash) if the issuer is unreachable.

**Flow:**
1. User clicks "Continue with Authentik"
2. `GET /api/auth/authentik/login` generates PKCE verifier/challenge + state,
   returns the Authentik authorization URL
3. Authentik redirects back to `/api/auth/authentik/callback` with a code
4. Podly exchanges the code for a token (PKCE verifier, no secret)
5. Session is created for the existing admin user (no new account)
6. Redirects to app

## Authentication Flows

### Login (Traditional)
```
POST /api/auth/login
{username: "user", password: "pass"}
→ Sets session cookie
→ Returns user info
```

### Login (Discord)
```
GET /api/discord/login
→ Redirect to Discord
→ GET /api/discord/callback
→ Sets session cookie
```

### Feed Access
```
GET /feed/TOKEN_ID:SECRET/rss
→ Validates token hash
→ Returns ad-free RSS
→ Updates last_used_at
```

## Rate Limiting

Authentication endpoints have rate limiting:

```python
# From auth/rate_limiter.py
- Login attempts: 5 per minute per IP
- Registration: 3 per hour per IP
- Password reset: 3 per hour per IP
```

Implements token bucket algorithm with Redis fallback to memory.

## Bootstrap Process

On first startup with auth enabled:
1. Check if admin user exists
2. Create admin from env vars if not
3. Set password from `PODLY_ADMIN_PASSWORD`
4. Log bootstrap event

## Guards & Decorators

### Route Protection
`require_admin` (`app/auth/guards.py`) is a function, not a decorator --
call it at the top of the route body and return its error response if present:
```python
from app.auth.guards import require_admin

def admin_route():
    user, error_response = require_admin("do the thing")
    if error_response:
        return error_response
    # Only admins reach here
```
All state-mutating routes should call this, including background-job
management (`/api/jobs/<id>/cancel`, `/api/jobs/cleanup/run` in
`routes/jobs_routes.py` -- previously missing this check entirely).

### Feed Access Check
```python
def is_feed_active_for_user(feed_id, user):
    # Check if feed within user's allowance
    # Based on subscription date ordering
```

Feed 1 is always treated as the default/landing feed regardless of
subscription state. This is centralized in `app/feeds.py:is_default_landing_feed()`
-- don't reintroduce inline `feed_id == 1` checks elsewhere.

## Security Considerations

- Passwords hashed with bcrypt
- Session secret key rotation support
- HTTPS recommended but HTTP allowed for self-hosting
- Feed tokens provide limited scope access
- Rate limiting prevents brute force
- No JWT (server-side sessions only)

## Configuration

**Environment Variables:**
```bash
REQUIRE_AUTH=true
PODLY_ADMIN_USERNAME=admin
PODLY_ADMIN_PASSWORD=secure_password
PODLY_SECRET_KEY=random_64_char_string

# Discord (optional)
DISCORD_CLIENT_ID=...
DISCORD_CLIENT_SECRET=...
DISCORD_REDIRECT_URI=https://example.com/api/discord/callback
DISCORD_GUILD_IDS=123456,789012

# Authentik (optional; public client, no secret)
AUTHENTIK_ISSUER=https://auth.example.com/application/o/<slug>/
AUTHENTIK_CLIENT_ID=...
AUTHENTIK_REDIRECT_URI=https://example.com/api/auth/authentik/callback
```

**Web UI Configuration:**
- Enable/disable auth (requires restart)
- Add/remove users
- Manage feed tokens
- View access logs
