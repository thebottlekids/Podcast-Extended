Project: Podcast-Extended (a fork of Podly)
Repository: https://github.com/thebottlekids/Podcast-Extended

**This is a fork of podly-pure-podcasts/podly_pure_podcasts**
All development work should target this fork, not the upstream repository.
The published image is `ghcr.io/thebottlekids/podcast-adblock` (`:lite` is the
variant deployed on Unraid). Pushing to `main` builds and publishes it.

Project-specific rules:
- Do not create Alembic migrations yourself; request the user to generate migrations after model changes.
- Only use ./scripts/ci.sh to run tests & lints - do not attempt to run directly
- use pipenv
- All database writes must go through the `writer` service. Do not use `db.session.commit()` directly in application code. Use `writer_client.action()` instead.
