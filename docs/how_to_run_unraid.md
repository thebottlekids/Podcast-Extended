# How to Run on Unraid

This guide covers running **Podcast-Extended** on Unraid via the **native Docker tab**. You do **not** need to be in the Community Applications store — a personal template works fine for a fork. (A Dockge compose stack is also provided at [`dockge/compose.yaml`](../dockge/compose.yaml) if you prefer compose; the steps below assume the native Docker tab, which is simpler for a single container.)

Because this is a fork with custom features (bulk feed editing, per-feed episode retention), the upstream image won't contain your changes — so you publish your own image to GHCR and Unraid pulls it.

All data, config, the SQLite database, and downloaded/processed audio live under a **single** App Data path, so backups and migrations are simple.

---

## 1. Get your image onto GHCR (the easy iteration loop)

The repo's workflow (`.github/workflows/docker-publish.yml`) builds and pushes to the GitHub Container Registry in two ways:

- **Every push to `main`** → builds the fast **`:lite`** image (no torch/whisper) and pushes `ghcr.io/thebottlekids/podcast-adblock:lite`.
- **On a published release** → builds the full variant matrix (CPU `:latest`, `:lite`, GPU) with version tags.

For day-to-day iteration you only need the first. Your loop is:

```
git push            # to main
# wait ~2-3 min for the Action to build :lite
# in Unraid: Docker tab → the container → Force Update
```

**One-time setup:** after the first build, make the package public so Unraid can pull without auth — GitHub → your profile → Packages → `podcast-adblock` → Package settings → Change visibility → **Public**. (If you keep it private, run `docker login ghcr.io` on the Unraid host once.)

> **Why `:lite`?** With Groq transcription and Ollama for ad detection you never run local Whisper, so the lite image drops torch/whisper — much smaller and faster to build and pull. If you ever want *local* Whisper on a GPU, publish a release and use the `gpu-nvidia` variant instead.

> **Prefer no registry?** Build on the box instead: `cd /mnt/user/appdata/Podcast-Extended && git pull && docker build --build-arg LITE_BUILD=true -t podcast-extended:local .`, then set the container's Repository to `podcast-extended:local`. Works, but building on Unraid is slower and less idiomatic than pulling.

---

## 2. Add the container in Unraid

1. Copy the template so Unraid sees it:
   ```bash
   mkdir -p /boot/config/plugins/dockerMan/templates-user
   cp /mnt/user/appdata/Podcast-Extended/unraid/podcast-extended.xml \
      /boot/config/plugins/dockerMan/templates-user/my-Podcast-Extended.xml
   ```
   (Or just fill the fields below manually via **Docker → Add Container**.)
2. Go to the **Docker** tab → **Add Container**.
3. In **Template**, pick **my-Podcast-Extended** (top of the list under "User templates").
4. Review the fields:

   | Field | Value | Notes |
   |-------|-------|-------|
   | Repository | `ghcr.io/thebottlekids/podcast-adblock:lite` | Or `podcast-extended:local` if you built on the box |
   | WebUI Port | `5001` | Change the host side if 5001 is taken |
   | App Data | `/mnt/user/appdata/podcast-extended` | Single path for DB, config, logs, audio |
   | PUID / PGID | `99` / `100` | Unraid defaults (nobody:users) |
   | GROQ_API_KEY | *your key* | Free at https://console.groq.com — covers transcription and (if no separate LLM key) ad detection |
   | WHISPER_TYPE | `groq` | Or `ollama` to use your local Ollama (see below) |

   Advanced fields (LLM key/model, auth, threads) are hidden under **Show advanced settings**.
5. Click **Apply**. The container starts, runs DB migrations automatically, and the UI is at `http://<unraid-ip>:5001/`.

---

## 3. Using your local Ollama for ad detection

There are two distinct compute jobs, and Ollama can only do one of them:

| Job | Backend |
|-----|---------|
| **Transcription** (Whisper) | Groq, a remote OpenAI-compatible Whisper server, or local Whisper. **Ollama cannot do this** — it has no audio/transcription endpoint. |
| **Ad detection** (LLM) | Any OpenAI-compatible chat model, including a local **Ollama** model. |

So the recommended self-hosted split is **Groq for transcription** (free, fast, no GPU needed on this box) and **Ollama for the LLM**.

To point ad detection at a local Ollama running on the same Unraid host:

1. Pull a chat model in your Ollama container, e.g.:
   ```bash
   docker exec -it ollama ollama pull llama3.1
   ```
2. Set these on the Podcast-Extended container (advanced fields in the template):
   - `OPENAI_BASE_URL` = `http://<unraid-ip>:11434/v1`  — use the host's **LAN IP**, not `localhost`, because the containers are on separate bridge networks. (Or put both on the same custom Docker network and use `http://ollama:11434/v1`.)
   - `LLM_API_KEY` = `ollama`  — any non-empty value; Ollama ignores it.
   - `LLM_MODEL` = `llama3.1`  — whatever you pulled.
3. Leave `WHISPER_TYPE=groq` so transcription continues to use Groq.

> **Want transcription fully local too?** Ollama still can't do it, but you can run a separate OpenAI-compatible Whisper server (e.g. [Speaches](https://github.com/speaches-ai/speaches), faster-whisper-server, or LocalAI) on your GPU. Then in **Settings → Whisper** choose the existing **remote** type and set its Base URL to that server's `/v1` endpoint, API key to anything non-empty, and the model name it serves. No GPU image needed for Podcast-Extended.

---

## 4. Updates and backups

- **Update**: `git push` to `main`, wait for the Action to rebuild `:lite`, then hit **Force Update** on the container in the Docker tab. (Or rebuild locally and restart.) Migrations run on start.
- **Backup**: stop the container and copy `/mnt/user/appdata/podcast-extended`. That folder is everything.
- **Auth**: leave `REQUIRE_AUTH=false` if the UI stays on your LAN. If you expose it (reverse proxy), see section 5 below.

---

## 5. Exposing to the internet (reverse proxy + auth)

> Skip this section if Podcast-Extended stays on your LAN.

### 5a. Container environment variables

Set all of these on the container before exposing it:

| Variable | Value | Notes |
|----------|-------|-------|
| `REQUIRE_AUTH` | `true` | Enables login. Without this, anyone can add feeds and enable episodes. |
| `PODLY_ADMIN_USERNAME` | *your username* | Admin account created on first start. Default: `podly_admin`. |
| `PODLY_ADMIN_PASSWORD` | *strong password* | Min 12 characters. Set this **before** first start — it only runs once. |
| `PODLY_SECRET_KEY` | *64-char random string* | Stable secret for signing sessions. Without it, sessions are lost on every restart. Generate with:<br>`python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `TRUSTED_PROXY_COUNT` | `1` | Tells the app to trust one reverse proxy hop. **Required** for per-client login rate-limiting to work correctly — without it, the proxy's IP gets blocked instead of the attacker's. |
| `PODLY_COOKIE_SECURE` | `true` | Marks session cookies as HTTPS-only. Requires your reverse proxy to terminate TLS. |

> **Important**: `PODLY_ADMIN_PASSWORD` is only read during the very first start when no users exist. To change it later, log in as admin and use Settings → Change Password (or the user management panel).

### 5b. Reverse proxy options

Pick whichever fits your setup. The app serves on port `5001` inside the container.

#### Option A — Cloudflare Tunnel (recommended, easiest, free)

No open ports on your router. Cloudflare handles TLS.

1. In Cloudflare Zero Trust → Networks → Tunnels → Create tunnel → Docker
2. Copy the `docker run` command Cloudflare gives you and run it on Unraid (or add it as a container)
3. Add a Public Hostname: domain `podcasts.yourdomain.com` → Service `http://unraid-ip:5001`
4. Done. Cloudflare terminates HTTPS before it ever reaches your LAN.

#### Option B — Nginx Proxy Manager (if you already have NPM on Unraid)

1. NPM → Proxy Hosts → Add
2. Domain: `podcasts.yourdomain.com`, Forward Host: `unraid-ip`, Forward Port: `5001`
3. SSL tab → Request Let's Encrypt cert → Force SSL ✓
4. You handle port-forwarding 80/443 on your router.

#### Option C — Caddy (lightweight, built-in HTTPS)

```
podcasts.yourdomain.com {
    reverse_proxy unraid-ip:5001
}
```

Caddy auto-obtains a cert via ACME. Requires ports 80/443 forwarded from your router.

### 5c. What the security stack looks like

```
Internet → Cloudflare / reverse proxy (TLS termination)
         → Unraid host port 5001
         → container port 5001
         → Flask app
              ├── auth middleware (session cookie, HttpOnly, SameSite=Lax)
              ├── login rate-limiter (exponential backoff, per client IP via ProxyFix)
              └── bcrypt password hashing (12 rounds)
```

No additional firewall rules are needed inside the container — the reverse proxy is the perimeter.
