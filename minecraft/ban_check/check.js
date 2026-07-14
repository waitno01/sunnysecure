#!/usr/bin/env node
/**
 * Connect to a Minecraft server with an existing MS access token (SSID)
 * via ColdProxy residential SOCKS5, and detect bans.
 *
 * Usage:
 *   node check.js --host mc.hypixel.net --token <ssid> --name <ign> --uuid <uuid>
 *     [--proxy host:port:user:pass] [--timeout 45000] [--attempts 3]
 *
 * stdout JSON:
 *   { "status": "ok"|"banned"|"error", "reason": "...", "ban_id": "...", "attempts": N }
 */
'use strict';

const mineflayer = require('mineflayer');
const { SocksClient } = require('socks');
const https = require('https');

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1) return fallback;
  return process.argv[i + 1] ?? fallback;
}

function stripColors(s) {
  return String(s || '').replace(/\u00a7[0-9a-fk-or]/gi, '').replace(/\s+/g, ' ').trim();
}

function formatKick(reason) {
  if (typeof reason === 'string') return stripColors(reason);
  if (reason && typeof reason === 'object') {
    if (typeof reason.translate === 'string') {
      const with = reason.with || reason['with'] || [];
      const extras = Array.isArray(with)
        ? with.map((x) => (typeof x === 'string' ? x : x?.text || '')).join(' ')
        : '';
      return stripColors(`${reason.translate} ${extras}`);
    }
    if (typeof reason.text === 'string' && reason.text) return stripColors(reason.text);
    try {
      return stripColors(JSON.stringify(reason));
    } catch (_) {
      return stripColors(String(reason));
    }
  }
  return stripColors(String(reason));
}

function extractBanId(text) {
  const m = String(text || '').match(/Ban\s*ID[^#A-Za-z0-9]*#?\s*([A-Za-z0-9]+)/i);
  return m ? m[1] : null;
}

function isBanMessage(text) {
  const lower = String(text || '').toLowerCase();
  if (!lower) return false;
  if (extractBanId(text)) return true;
  return (
    /\bbanned\b/.test(lower) ||
    /\bban\s*id\b/.test(lower) ||
    /\bterminated\b/.test(lower) ||
    /\bblocked\b/.test(lower) ||
    /\bblacklist/.test(lower) ||
    lower.includes('you are permanently') ||
    lower.includes('you have been banned') ||
    lower.includes('your account has been') ||
    lower.includes('security ban')
  );
}

function isTransientKick(text) {
  const lower = String(text || '').toLowerCase();
  if (isBanMessage(text)) return false;
  return (
    lower.includes('timed out') ||
    lower.includes('timeout') ||
    lower.includes('connection reset') ||
    lower.includes('connection refused') ||
    lower.includes('failed to verify') ||
    lower.includes('failed to authenticate') ||
    lower.includes('authentication') ||
    lower.includes('proxy') ||
    lower.includes('throttl') ||
    lower.includes('rate limit') ||
    lower.includes('try again') ||
    lower.includes('server is full') ||
    lower.includes('restart') ||
    lower.includes('offline') ||
    lower.includes('econn') ||
    lower.includes('socket') ||
    lower.includes('internal exception') ||
    lower.includes('io.netty') ||
    lower.includes('read timed') ||
    lower.includes('closed') ||
    lower.includes('encrypted') ||
    lower.includes('invalid session')
  );
}

function parseProxy(line) {
  if (!line) return null;
  const parts = String(line).split(':');
  if (parts.length < 4) return null;
  return {
    host: parts[0],
    port: parseInt(parts[1], 10) || 0,
    userId: parts[2],
    password: parts.slice(3).join(':'),
  };
}

function fetchProfile(token) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: 'api.minecraftservices.com',
        path: '/minecraft/profile',
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
        timeout: 20000,
      },
      (res) => {
        let body = '';
        res.on('data', (c) => (body += c));
        res.on('end', () => {
          try {
            const j = JSON.parse(body || '{}');
            if (!j.name || !j.id) return reject(new Error('No Java profile on this SSID'));
            resolve({ name: j.name, uuid: j.id });
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('profile fetch timeout'));
    });
    req.end();
  });
}

function createSessionAuthHandler(session) {
  return (client, options) => {
    if (!session?.accessToken || !session?.selectedProfile?.name) {
      client.emit('error', new Error('Missing Minecraft session'));
      return;
    }
    client.session = session;
    client.username = session.selectedProfile.name;
    options.accessToken = session.accessToken;
    options.haveCredentials = true;
    options.skipValidation = true;
    client.emit('session', session);
    options.connect(client);
  };
}

function attemptConnect({ host, port, token, name, uuid, proxy, timeoutMs }) {
  return new Promise((resolve) => {
    let settled = false;
    let bot = null;
    const done = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        bot?.quit?.('done');
      } catch (_) {}
      try {
        bot?.end?.();
      } catch (_) {}
      resolve(result);
    };

    const timer = setTimeout(() => {
      done({ status: 'error', reason: `Timed out after ${timeoutMs}ms waiting for spawn/kick` });
    }, timeoutMs);

    const session = {
      accessToken: token,
      clientToken: 'autosecure-ban-check',
      selectedProfile: {
        id: String(uuid).replace(/-/g, ''),
        name,
      },
    };

    const opts = {
      host,
      port,
      username: name,
      version: false,
      hideErrors: true,
      checkTimeoutInterval: Math.min(timeoutMs, 90000),
      auth: createSessionAuthHandler(session),
    };

    if (proxy) {
      opts.connect = (client) => {
        SocksClient.createConnection(
          {
            proxy: {
              host: proxy.host,
              port: proxy.port,
              type: 5,
              userId: proxy.userId || undefined,
              password: proxy.password || undefined,
            },
            command: 'connect',
            destination: { host, port },
            timeout: Math.min(timeoutMs, 30000),
          },
          (err, info) => {
            if (err) {
              done({ status: 'error', reason: `Proxy connect failed: ${err.message || err}` });
              return;
            }
            client.setSocket(info.socket);
            client.emit('connect');
          }
        );
      };
    }

    try {
      bot = mineflayer.createBot(opts);
    } catch (e) {
      done({ status: 'error', reason: e.message || String(e) });
      return;
    }

    bot.once('spawn', () => {
      done({ status: 'ok', reason: 'spawned' });
    });

    bot.once('login', () => {
      setTimeout(() => {
        if (!settled) done({ status: 'ok', reason: 'logged_in' });
      }, 5000);
    });

    bot.on('kicked', (reason) => {
      const text = formatKick(reason);
      const banId = extractBanId(text);
      if (isBanMessage(text)) {
        done({ status: 'banned', reason: text, ban_id: banId });
      } else {
        done({ status: 'error', reason: text || 'kicked' });
      }
    });

    bot.on('end', (reason) => {
      if (settled) return;
      const text = formatKick(reason);
      if (isBanMessage(text)) {
        done({
          status: 'banned',
          reason: text || 'disconnected (ban)',
          ban_id: extractBanId(text),
        });
      } else {
        done({ status: 'error', reason: text || 'disconnected' });
      }
    });

    bot.on('error', (err) => {
      if (settled) return;
      done({ status: 'error', reason: err?.message || String(err) });
    });
  });
}

async function main() {
  const host = arg('host');
  const token = arg('token');
  const timeoutMs = parseInt(arg('timeout', '45000'), 10) || 45000;
  const maxAttempts = Math.max(1, parseInt(arg('attempts', '3'), 10) || 3);
  const port = parseInt(arg('port', '25565'), 10) || 25565;
  let name = arg('name');
  let uuid = arg('uuid');
  const proxy = parseProxy(arg('proxy'));

  if (!host || !token) {
    console.log(JSON.stringify({ status: 'error', reason: 'Missing --host or --token' }));
    process.exit(0);
  }

  try {
    if (!name || !uuid) {
      const profile = await fetchProfile(token);
      name = name || profile.name;
      uuid = uuid || profile.uuid;
    }
  } catch (e) {
    console.log(
      JSON.stringify({ status: 'error', reason: e.message || String(e), attempts: 0 })
    );
    process.exit(0);
  }

  let last = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    last = await attemptConnect({
      host,
      port,
      token,
      name,
      uuid,
      proxy,
      timeoutMs,
    });
    last.attempts = attempt;
    last.name = name;
    last.uuid = uuid;

    if (last.status === 'ok' || last.status === 'banned') {
      console.log(JSON.stringify(last));
      process.exit(0);
    }
    if (attempt < maxAttempts) {
      await new Promise((r) => setTimeout(r, 1500 * attempt));
      continue;
    }
    break;
  }

  // After max retries: assume banned and surface kick/error reason
  last = {
    status: 'banned',
    reason: `Assumed banned after ${last?.attempts || maxAttempts} failed joins: ${last?.reason || 'unknown'}`,
    ban_id: extractBanId(last?.reason),
    attempts: last?.attempts || maxAttempts,
    name,
    uuid,
    assumed: true,
  };
  console.log(JSON.stringify(last));
  process.exit(0);
}

main().catch((e) => {
  console.log(JSON.stringify({ status: 'error', reason: e.message || String(e) }));
  process.exit(0);
});
