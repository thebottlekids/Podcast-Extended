# OPML Subscription Export

## Status

Planned. No implementation has started.

This feature should be developed separately from the completed beta-hardening
work. The beta-hardening fixes have already passed the full sanctioned backend
checks, frontend build checks, and an isolated Unraid Docker smoke test. The
core application functions are working, and no additional broad hardening test
cycle is planned. This feature will receive focused verification for the code
and behavior it introduces.

## Goal

Allow a user to download all podcasts visible to them as an OPML 2.0 file and
import those subscriptions into AntennaPod or another OPML-compatible podcast
application.

Each podcast must remain a separate subscription. Exported subscriptions must
use Podcast-Extended's generated, ad-free RSS feeds rather than the publishers'
original RSS URLs.

## Non-goals

- Exporting played/unplayed state, playback position, history, favorites,
  queue contents, downloaded audio, or podcast-app settings.
- Replacing or changing the existing aggregate RSS feed.
- Adding an OPML import feature to Podcast-Extended.
- Changing the feed-token schema or adding a database migration.
- Deploying the feature to the live container as part of implementation.

## User experience

Add an **Export OPML** action near the existing aggregate-feed action on the
Podcast Feeds page.

When selected, the browser downloads:

```text
podcast-extended-subscriptions.opml
```

The action should show a loading/disabled state while the export is generated,
then report success or use the existing diagnostic error flow on failure.

The interface should warn the user that, when authentication is enabled, the
file contains private feed credentials. The user should store it securely and
delete it after importing it into their podcast app.

## Feed selection

The export must follow the same visibility rules as the existing feed list:

- **Administrator:** all feeds.
- **Regular authenticated user:** feeds joined by that user, plus the default
  landing feed when applicable.
- **Authentication disabled:** all feeds.

Results should use a deterministic ordering, preferably case-insensitive feed
title followed by feed ID, so repeated exports are stable.

An account with no visible feeds should receive a valid OPML file with an empty
body rather than an error.

## API contract

Add an authenticated download endpoint:

```http
POST /api/user/opml-export
```

`POST` is appropriate because generating an authenticated export can create a
missing feed access token. The operation is otherwise idempotent: existing
active tokens are reused.

Successful response headers:

```http
Content-Type: text/x-opml; charset=utf-8
Content-Disposition: attachment; filename="podcast-extended-subscriptions.opml"
Cache-Control: no-store
```

Expected errors:

- `401` when authentication is enabled and no valid session is present.
- `500` with a generic response if token generation or OPML generation fails;
  secrets must not appear in the response or logs.

## OPML format

Generate OPML with Python's standard XML APIs rather than string
concatenation. This ensures feed titles and URLs containing ampersands, quotes,
Unicode, or other special characters are escaped correctly.

Example structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head>
    <title>Podcast-Extended Subscriptions</title>
  </head>
  <body>
    <outline
      text="Example Podcast"
      title="Example Podcast"
      type="rss"
      xmlUrl="https://podcast.example/feed/12?feed_token=...&amp;feed_secret=..." />
  </body>
</opml>
```

Each outline must contain:

- `text`: feed title.
- `title`: feed title.
- `type="rss"`.
- `xmlUrl`: Podcast-Extended's generated RSS URL.

Include `htmlUrl` only if Podcast-Extended has a meaningful public show-page
URL. Do not substitute the publisher's original RSS URL.

## Feed credentials

When authentication is enabled, each `xmlUrl` must contain the existing
`feed_token` and `feed_secret` query parameters required by podcast clients.

Use the current one-active-token-per-user-and-feed behavior:

- Reuse an existing active token and secret.
- Create a token only when none exists.
- Do not mint a new set of tokens on every export.
- Do not use the user's session cookie or primary password in the OPML file.

Add a bulk writer action that creates or retrieves tokens for all selected feed
IDs in one writer transaction. All database writes must remain in the writer
service. The route must decide which feed IDs the user may export before
calling the writer action.

When authentication is disabled, emit local Podcast-Extended feed URLs without
credential query parameters.

## Backend work

1. Extract or reuse a helper for determining feeds visible to the current user
   so `/feeds` and the OPML export cannot drift apart.
2. Add and register a bulk writer action for retrieving or creating stable feed
   access tokens.
3. Add an OPML-generation helper with deterministic ordering and safe XML
   serialization.
4. Add `POST /api/user/opml-export` to the feed routes or a suitably scoped
   export route module.
5. Build feed URLs from the externally visible request origin, respecting the
   application's existing reverse-proxy handling.
6. Ensure error messages and logs never include token secrets or the completed
   OPML document.

No model change or Alembic migration is expected.

## Frontend work

1. Add an API-client method that requests the OPML response as a blob.
2. Read the response filename when available and trigger a browser download.
3. Add the Export OPML action beside the aggregate-feed action.
4. Add an accessible label/title, loading state, and duplicate-click
   protection.
5. Use the existing toast and diagnostic error patterns.
6. Surface the credential warning without requiring the user to understand
   token implementation details.

## Focused verification

Backend tests should cover:

- Authentication is required when enabled.
- An administrator exports all feeds.
- A regular user exports only visible feeds plus the default landing feed.
- No-auth mode exports all feeds without credentials.
- A valid empty OPML document is returned when no feeds exist.
- The response content type, download filename, and `no-store` header.
- Each outline has the expected title, type, and Podcast-Extended URL.
- Special characters and Unicode produce valid XML.
- Exported token credentials allow anonymous RSS and episode-download access.
- Repeated exports reuse the same token for each user/feed pair.
- Token-generation failure does not return a partial file or expose secrets.
- Existing individual share links and aggregate feeds continue to work.

Frontend verification should cover:

- The action downloads the returned file.
- The button cannot launch duplicate concurrent exports.
- Success and failure feedback follow existing UI behavior.
- The layout remains usable at desktop and mobile widths.

Run only the repository-sanctioned test command:

```bash
./scripts/ci.sh
```

Because Node and Docker are unavailable on the Windows development machine,
perform the frontend build and final browser/import smoke test in an isolated,
throwaway environment on the Unraid host. Do not modify or restart the live
Podcast-Extended container during feature verification.

## Manual acceptance test

1. Create an isolated build from the feature branch on Unraid.
2. Add feeds whose titles include ordinary text, `&`, quotes, and Unicode.
3. Download the OPML file while authenticated.
4. Import it into AntennaPod.
5. Confirm every show appears as a separate subscription.
6. Refresh multiple subscriptions and confirm RSS and artwork load.
7. Download or stream an episode and confirm its media URL resolves through
   Podcast-Extended.
8. Export again and confirm the same token IDs are reused.
9. Remove the throwaway container and build artifacts after verification.

## Delivery sequence

1. Review and merge `harden/beta-fixes` into `main` after explicit user
   approval.
2. Create `feature/opml-export` from the updated `main`.
3. Implement the backend, focused tests, frontend action, and user docs.
4. Run the sanctioned checks and isolated Unraid verification.
5. Review and merge the feature separately.
6. Treat deployment to the live Podcast-Extended container as a separate,
   explicit decision.

## Acceptance criteria

- A user can download one valid OPML file containing every podcast visible to
  them as a separate subscription.
- AntennaPod can import the file without manual URL editing.
- Imported shows use Podcast-Extended's ad-free RSS and media URLs.
- Regular users cannot export inaccessible feeds.
- Repeated exports do not create duplicate active credentials.
- Secrets are not exposed in logs, errors, or cacheable responses.
- No database migration is introduced.
- Existing feed sharing and aggregate-feed behavior remain unchanged.
