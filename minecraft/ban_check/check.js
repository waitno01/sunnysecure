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
  if (typeof reason === 'string') {
    // Mineflayer sometimes stringifies NBT compounds
    if (reason.includes('"type":"compound"') || reason.includes('"Ban ID"')) {
      try {
        const texts = [...reason.matchAll(/"text"\s*:\s*\{\s*"type"\s*:\s*"string"\s*,\s*"value"\s*:\s*"((?:\\.|[^"\\])*)"/g)]
          .map((m) => m[1].replace(/\\n/g, '\n').replace(/\\"/g, '"'));
        if (texts.length) return stripColors(texts.join(''));
      } catch (_) {}
    }
    return stripColors(reason);
  }
  if (reason && typeof reason === 'object') {
    if (typeof reason.translate === 'string') {
      const withArgs = reason.with || reason['with'] || [];
      const extras = Array.isArray(withArgs)
        ? withArgs.map((x) => (typeof x === 'string' ? x : x?.text || '')).join(' ')
        : '';
      return stripColors(`${reason.translate} ${extras}`);
    }
    if (typeof reason.text === 'string' && reason.text) return stripColors(reason.text);
    // Walk chat components / NBT-ish objects for nested text
    try {
      const parts = [];
      const walk = (node) => {
        if (!node) return;
        if (typeof node === 'string') {
          parts.push(node);
          return;
        }
        if (typeof node !== 'object') return;
        if (typeof node.text === 'string') parts.push(node.text);
        if (typeof node.value === 'string') parts.push(node.value);
        if (Array.isArray(node.extra)) node.extra.forEach(walk);
        if (node.extra && typeof node.extra === 'object' && node.extra.value) walk(node.extra.value);
        if (Array.isArray(node.value)) node.value.forEach(walk);
        if (node.value && typeof node.value === 'object' && !Array.isArray(node.value)) walk(node.value);
      };
      walk(reason);
      if (parts.length) return stripColors(parts.join(''));
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
  const lower = String(text || '').toLowerCase().replace(/\s+/g, '');
  if (isBanMessage(text)) return false;
  const raw = String(text || '').toLowerCase();
  return (
    lower === 'socketclosed' ||
    lower.includes('socketclosed') ||
    raw.includes('timed out') ||
    raw.includes('timeout') ||
    raw.includes('connection reset') ||
    raw.includes('connection refused') ||
    raw.includes('failed to verify') ||
    raw.includes('failed to authenticate') ||
    raw.includes('authentication') ||
    raw.includes('proxy') ||
    raw.includes('throttl') ||
    raw.includes('rate limit') ||
    raw.includes('try again') ||
    raw.includes('server is full') ||
    raw.includes('restart') ||
    raw.includes('offline') ||
    raw.includes('econn') ||
    raw.includes('socket') ||
    raw.includes('internal exception') ||
    raw.includes('io.netty') ||
    raw.includes('read timed') ||
    raw.includes('closed') ||
    raw.includes('encrypted') ||
    raw.includes('invalid session') ||
    raw.includes('disconnected')
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

    // Capture disconnect/kick packets BEFORE mineflayer collapses them to "socketClosed"
    let lastDisconnectReason = null;
    const rememberDisconnect = (packet) => {
      try {
        const reason = packet?.reason ?? packet;
        const text = formatKick(reason);
        if (text && text.toLowerCase() !== 'socketclosed') {
          lastDisconnectReason = reason;
        }
      } catch (_) {}
    };
    const client = bot._client;
    if (client) {
      client.on('kick_disconnect', rememberDisconnect);
      client.on('disconnect', rememberDisconnect);
      // Some versions emit raw packet names differently
      client.on('packet', (data, meta) => {
        if (!meta || !meta.name) return;
        if (meta.name === 'kick_disconnect' || meta.name === 'disconnect') {
          rememberDisconnect(data);
        }
      });
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
      lastDisconnectReason = reason;
      const text = formatKick(reason);
      const banId = extractBanId(text);
      if (isBanMessage(text)) {
        done({ status: 'banned', reason: text, ban_id: banId });
      } else {
        done({ status: 'error', reason: text || 'kicked' });
      }
    });

    bot.on('end', (reason) => {
      // Brief delay so 'kicked' / kick_disconnect can win the race over socketClosed
      setTimeout(() => {
        if (settled) return;
        const prefer = lastDisconnectReason != null ? lastDisconnectReason : reason;
        const text = formatKick(prefer);
        if (isBanMessage(text)) {
          done({
            status: 'banned',
            reason: text || 'disconnected (ban)',
            ban_id: extractBanId(text),
          });
        } else {
          done({ status: 'error', reason: text || 'disconnected' });
        }
      }, 150);
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

  // After max retries: only assume banned when we saw ban-like text.
  // Bare socketClosed / proxy drops stay as soft errors (do not reject sells).
  const finalReason = last?.reason || 'unknown';
  if (isBanMessage(finalReason)) {
    last = {
      status: 'banned',
      reason: finalReason,
      ban_id: extractBanId(finalReason),
      attempts: last?.attempts || maxAttempts,
      name,
      uuid,
    };
  } else if (isTransientKick(finalReason)) {
    last = {
      status: 'error',
      reason: `Join failed after ${last?.attempts || maxAttempts} attempts (transient): ${finalReason}`,
      attempts: last?.attempts || maxAttempts,
      name,
      uuid,
      assumed: false,
    };
  } else {
    last = {
      status: 'banned',
      reason: `Assumed banned after ${last?.attempts || maxAttempts} failed joins: ${finalReason}`,
      ban_id: extractBanId(finalReason),
      attempts: last?.attempts || maxAttempts,
      name,
      uuid,
      assumed: true,
    };
  }
  console.log(JSON.stringify(last));
  process.exit(0);
}

main().catch((e) => {
  console.log(JSON.stringify({ status: 'error', reason: e.message || String(e) }));
  process.exit(0);
});
