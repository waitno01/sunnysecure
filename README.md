# AutoSecure (fork)

Fork of [saldevsautosec/autosecure](https://github.com/saldevsautosec/autosecure) — maintained by [waitno01/autosecure](https://github.com/waitno01/autosecure).

Request-based Microsoft account securing for Discord, with a built-in SMTP server and web dashboard. No Selenium or Playwright.

---

## Fork changes

This fork adds fixes and features on top of upstream:

| Area | Change |
|------|--------|
| **Mail** | Built-in Discord webhook forwarding + OTP detection (no separate `smtp-discord` needed) |
| **Mail** | Optional playtime OTP bridge (`mail.otp_bridge_url` in config) |
| **Securing** | Failure DMs include security email, password, and recovery code when recovery already ran |
| **Securing** | Lock/suspended/phone-locked detection before and during secure (uses `/check locked` API) |
| **Securing** | Bedrock / Game Pass accounts without a Java profile handled without crashing |
| **Securing** | Safer embed building (missing subscription/cape fields, partial success embeds) |
| **Dashboard** | Delete accounts from list + database |
| **Ops** | PM2 `ecosystem.config.cjs` for bot, API, and web |
| **Ops** | `setup.sh` for venv, web build, and PM2 start |

Upstream Discord invite and original docs are not affiliated with this fork.

---

## Table of contents

- [Requirements](#requirements)
- [Quick setup](#quick-setup)
- [Configuration](#configuration)
- [Email & DNS](#email--dns)
- [Running with PM2](#running-with-pm2)
- [Web dashboard](#web-dashboard)
- [Bot commands](#bot-commands)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)

---

## Requirements

| Dependency | Version | Purpose |
|------------|---------|---------|
| Python | 3.12+ | Bot, API, securing logic, SMTP |
| Node.js | 20+ (22 recommended for web build) | Dashboard frontend |
| PM2 | latest | Process manager |
| Port 25 | open | Inbound SMTP for security emails |

---

## Quick setup

```bash
git clone https://github.com/waitno01/autosecure.git
cd autosecure

# Create config (never commit this file)
cp config/config.json.example config/config.json   # if example exists
# otherwise create config/config.json — see Configuration below

# Python deps (3.12+)
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Web dashboard
cd web && npm install && npm run build && cd ..

# Start everything
pm2 start ecosystem.config.cjs
pm2 save
```

Or use the helper script (edit Python version in `setup.sh` if your VPS does not have 3.14):

```bash
./setup.sh
```

---

## Configuration

Two config files control runtime behavior. **`config/config.json` is gitignored** — create it locally and keep secrets out of git.

### `config/config.json`

```json
{
  "owners": [ YOUR_DISCORD_ID ],
  "tokens": {
    "bot_token": "YOUR_BOT_TOKEN",
    "skytools_key": "",
    "donut_key": ""
  },
  "discord": {
    "logs_channel": "",
    "accounts_channel": "",
    "censored_logs_channel": ""
  },
  "autosecure": {
    "replace_main_alias": true,
    "enable_2fa": true,
    "minecon_mode": false
  },
  "web": {
    "credentials": {
      "username": "admin",
      "password": "CHANGE_ME",
      "jwt_secret": "GENERATE_A_LONG_RANDOM_STRING"
    }
  },
  "domain": "yourdomain.com",
  "mail": {
    "discord_webhook_all": "https://discord.com/api/webhooks/...",
    "discord_webhook_otp": "https://discord.com/api/webhooks/...",
    "otp_bridge_url": "http://127.0.0.1:12798/otp",
    "otp_bridge_token": ""
  }
}
```

| Key | Description |
|-----|-------------|
| `domain` | Domain for auto-created security emails (`alias@yourdomain.com`) |
| `mail.discord_webhook_all` | Discord webhook for every incoming email |
| `mail.discord_webhook_otp` | Discord webhook when an OTP is detected |
| `mail.otp_bridge_url` | Optional HTTP endpoint (e.g. playtime OTP bridge) |
| `web.credentials` | Dashboard login + JWT secret |
| `autosecure.*` | Alias replacement, 2FA, minecon mode |

### `config/bot.json`

Command toggles, aliases, embed templates, button labels, presence, and post-verification behavior. Tracked in git (no secrets).

### Discord bot setup

1. [Discord Developer Portal](https://discord.com/developers/applications) → create app → **Bot**
2. Enable all **Privileged Gateway Intents**
3. OAuth2 URL Generator: scopes `bot` + `applications.commands`, invite to your server
4. Put the bot token in `config/config.json`

### API keys (optional)

| Service | URL | Used for |
|---------|-----|----------|
| Skytools | [developer.skytools.app](https://developer.skytools.app/) | Hypixel / SkyBlock stats |
| DonutSMP | [api.donutsmp.net](https://api.donutsmp.net/index.html) | Donut stats |

---

## Email & DNS

The bot runs an SMTP server on **port 25** when `autosecure-bot` starts. Mail is stored in SQLite and forwarded to Discord webhooks.

### Cloudflare DNS (DNS only / grey cloud)

| Type | Name | Value |
|------|------|-------|
| A | `mail` | Your VPS public IP |
| MX | `@` | `mail.yourdomain.com` (priority 10) |

Only one process should bind port 25 on the VPS (this bot — not a separate smtp-discord instance).

---

## Running with PM2

`ecosystem.config.cjs` starts three processes:

| Process | Port | Role |
|---------|------|------|
| `autosecure-bot` | 25 (SMTP) | Discord bot + mail server |
| `autosecure-api` | 8000 | FastAPI backend |
| `autosecure-web` | 3000 | Dashboard (Nitro build) |

```bash
pm2 start ecosystem.config.cjs
pm2 logs autosecure-bot
pm2 restart autosecure-bot autosecure-api autosecure-web
```

Update `CORS_ORIGINS` in `ecosystem.config.cjs` if you access the dashboard from a public IP or domain.

### Public access (optional)

Use Cloudflare Tunnel or nginx in front of ports 3000/8000. See upstream `cloudflared.yml` if you use a tunnel.

---

## Web dashboard

Default: `http://YOUR_VPS_IP:3000` (or your tunnel/domain).

| Tab | Description |
|-----|-------------|
| Overview | Stats and recent accounts |
| Accounts | Browse, search, view details, **delete** accounts |
| Secure | Manual / bulk securing |
| Emails | Security inboxes |
| Bot Config | Channels, commands, embeds |
| Settings | Dashboard password / 2FA |

Login uses `web.credentials` from `config/config.json`.

---

## Bot commands

Command names can be renamed in `config/bot.json` or the dashboard.

| Command | Description |
|---------|-------------|
| `/secure` | Secure via recovery code or auth+password |
| `/check locked` | Check suspended / phone-locked status (admin) |
| `/email new` | Create `alias@domain` security email |
| `/email inbox` | View inbox for a security email |
| `/email list` | List stored security emails |
| `/request_otp` | Request OTP / 2FA bypass flow |
| `/auth code` | TOTP from 2FA secret |
| `/set channel` | Set logs / hits channels |
| `/send embed` | Send verification embed |
| `/stats hypixel` / `/stats donut` | Minecraft stats (needs API keys) |

---

## Troubleshooting

| Problem | What to check |
|---------|----------------|
| Bot won't start | Python 3.12+, venv deps, valid `bot_token`, intents enabled |
| Port 25 in use | Stop other SMTP (`pm2 stop mail` / smtp-discord); only one listener |
| Emails not arriving | DNS A/MX, port 25 open, `domain` in config matches MX domain |
| Wrong failure message on locked account | Re-pull this fork — lock detection runs before secure |
| Dashboard login fails | `web.credentials` in `config/config.json` |
| `git push` goes to wrong host | `git remote set-url origin https://github.com/waitno01/autosecure.git` |
| Web build fails on Node 20 | Run `node node_modules/vite/bin/vite.js build` inside `web/` |

---

## Disclaimer

Use at your own risk. Automating Microsoft account flows may violate Microsoft's Terms of Service. This software is for educational purposes. The fork maintainers and upstream authors are not responsible for account actions taken by Microsoft or third parties.

**Do not commit** `config/config.json`, `.env`, or `database/database.db` — they contain secrets and secured account data.
