/**
 * MP.AI WhatsApp QR microservice (Baileys multi-device).
 *
 * - WebSocket `/ws/qr/:botId` streams QR / connection status to FastAPI (proxied to Next.js)
 * - POST `/api/send-message` sends outbound text for a bot session
 * - Inbound WhatsApp messages are forwarded to FastAPI `/api/v1/webhooks/whatsapp-qr`
 */

"use strict";

require("dotenv").config();

const fs = require("fs");
const path = require("path");
const http = require("http");
const crypto = require("crypto");
const express = require("express");
const cors = require("cors");
const WebSocket = require("ws");
const axios = require("axios");
const pino = require("pino");
const QRCode = require("qrcode");
const { Boom } = require("@hapi/boom");

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} = require("@whiskeysockets/baileys");

const PORT = Number(process.env.PORT || 3001);
const HOST = process.env.HOST || "0.0.0.0";
const FASTAPI_WEBHOOK_URL =
  process.env.FASTAPI_WEBHOOK_URL || "http://127.0.0.1:8000/api/v1/webhooks/whatsapp-qr";
const INTERNAL_SERVICE_API_KEY =
  process.env.INTERNAL_SERVICE_API_KEY || process.env.SERVICE_API_KEY || "";
const SESSIONS_DIR = path.resolve(
  process.env.SESSIONS_DIR || path.join(__dirname, "whatsapp-sessions"),
);

const logger = pino({ level: process.env.LOG_LEVEL || "info" });

fs.mkdirSync(SESSIONS_DIR, { recursive: true });

const IS_PRODUCTION =
  String(process.env.NODE_ENV || "").toLowerCase() === "production" ||
  String(process.env.ENVIRONMENT || "").toLowerCase() === "production";

function timingSafeEqualString(a, b) {
  const left = Buffer.from(String(a || ""), "utf8");
  const right = Buffer.from(String(b || ""), "utf8");
  if (left.length !== right.length) return false;
  return crypto.timingSafeEqual(left, right);
}

function extractInternalKey(reqOrHeaders) {
  const headers = reqOrHeaders.headers || reqOrHeaders || {};
  const auth = String(headers["authorization"] || headers["Authorization"] || "");
  const bearer = auth.toLowerCase().startsWith("bearer ")
    ? auth.slice(7).trim()
    : "";
  return (
    String(headers["x-internal-api-key"] || headers["x-service-api-key"] || "").trim() ||
    bearer
  );
}

function requireInternalAuth(req, res, next) {
  if (!INTERNAL_SERVICE_API_KEY) {
    if (IS_PRODUCTION) {
      logger.error("INTERNAL_SERVICE_API_KEY missing — refusing API request in production");
      return res.status(503).json({ ok: false, error: "auth_not_configured" });
    }
    return next();
  }
  const provided = extractInternalKey(req);
  if (!provided || !timingSafeEqualString(provided, INTERNAL_SERVICE_API_KEY)) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  return next();
}

function authorizeUpgrade(request) {
  if (!INTERNAL_SERVICE_API_KEY) {
    if (IS_PRODUCTION) return false;
    return true;
  }
  const headerKey = extractInternalKey(request);
  if (headerKey && timingSafeEqualString(headerKey, INTERNAL_SERVICE_API_KEY)) {
    return true;
  }
  try {
    const url = new URL(request.url || "", "http://localhost");
    const q =
      url.searchParams.get("internal_key") ||
      url.searchParams.get("token") ||
      "";
    if (q && timingSafeEqualString(q, INTERNAL_SERVICE_API_KEY)) return true;
  } catch (_) {
    /* ignore */
  }
  return false;
}

/** @type {Map<string, { sock: any, status: string, qrBase64: string|null, phone: string|null, pushName: string|null, connectedAt: string|null, starting: boolean, reconnectAttempt: number, reconnectTimer: any, lastQrAt: number, lastQrRaw: string|null }>} */
const sessions = new Map();

/** @type {Map<string, Set<WebSocket>>} */
const qrClients = new Map();

/** Stage 5 canonical events + legacy aliases for existing FE/proxy. */
const SESSION_EVENTS = {
  QR_READY: { primary: "QR_READY", legacy: "qr_code_ready" },
  CONNECTED: { primary: "CONNECTED", legacy: "session_connected" },
  DISCONNECTED: { primary: "DISCONNECTED", legacy: "connection_failed" },
  AUTH_FAILURE: { primary: "AUTH_FAILURE", legacy: "connection_failed" },
  SCANNING: { primary: "CONNECTED", legacy: "scanning_detected" }, // brief interim uses legacy only below
};

function sessionPath(botId) {
  return path.join(SESSIONS_DIR, String(botId));
}

function broadcast(botId, frame) {
  const clients = qrClients.get(String(botId));
  if (!clients || clients.size === 0) return;
  const payload = JSON.stringify(frame);
  for (const client of clients) {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  }
}

/** Emit Stage 5 event name while keeping legacy `event` consumers working via dual fields. */
function emitSession(botId, eventKey, frame) {
  const mapping = SESSION_EVENTS[eventKey] || { primary: eventKey, legacy: eventKey };
  broadcast(botId, {
    ...frame,
    event: mapping.primary,
    legacy_event: mapping.legacy,
  });
  // Also emit legacy-named frame for older clients that switch only on `event`.
  if (mapping.legacy && mapping.legacy !== mapping.primary) {
    broadcast(botId, {
      ...frame,
      event: mapping.legacy,
      legacy_event: mapping.legacy,
    });
  }
}

function backoffDelayMs(attempt) {
  // Exponential: 1s, 2s, 4s, 8s, 16s, cap 30s
  const exp = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt - 1));
  const jitter = Math.floor(Math.random() * 250);
  return exp + jitter;
}

async function qrStringToBase64Png(qr) {
  const dataUrl = await QRCode.toDataURL(qr, {
    errorCorrectionLevel: "M",
    margin: 2,
    width: 320,
    color: { dark: "#000000", light: "#ffffff" },
  });
  return dataUrl.replace(/^data:image\/png;base64,/, "");
}

function jidToPhone(jid) {
  if (!jid) return "";
  return String(jid).split("@")[0].split(":")[0];
}

async function forwardInboundToFastAPI(botId, message, pushName) {
  const from = jidToPhone(message.key?.remoteJid);
  let messageText = "";
  const contentType = Object.keys(message.message || {})[0] || "unknown";

  if (message.message?.conversation) {
    messageText = message.message.conversation;
  } else if (message.message?.extendedTextMessage?.text) {
    messageText = message.message.extendedTextMessage.text;
  } else if (message.message?.imageMessage?.caption) {
    messageText = `[User sent image] ${message.message.imageMessage.caption}`;
  } else {
    messageText = `[User sent ${contentType}]`;
  }

  if (!from || !messageText.trim()) {
    return;
  }

  const body = {
    bot_id: String(botId),
    from,
    message_text: messageText.trim(),
    message_id: message.key?.id || null,
    push_name: pushName || from,
    content_type: contentType,
    remote_jid: message.key?.remoteJid || null,
  };

  try {
    const headers = {};
    if (INTERNAL_SERVICE_API_KEY) {
      headers["X-Internal-Api-Key"] = INTERNAL_SERVICE_API_KEY;
    }
    await axios.post(FASTAPI_WEBHOOK_URL, body, { timeout: 15000, headers });
    logger.info({ botId, from }, "forwarded inbound message to FastAPI");
  } catch (err) {
    logger.error(
      { botId, from, err: err?.message || String(err) },
      "failed to forward inbound WhatsApp message",
    );
  }
}

const QR_BROADCAST_MIN_INTERVAL_MS = 20_000;

async function startSession(botId, options = {}) {
  const force = Boolean(options.force);
  const key = String(botId);
  const existing = sessions.get(key);

  if (existing?.starting) {
    return existing;
  }

  // Never tear down a live Baileys session just because a browser WS (re)connected.
  if (!force && existing?.sock && existing.status === "connected") {
    emitSession(key, "CONNECTED", {
      status: "connected",
      qr_base64: null,
      message: "WhatsApp уже подключён.",
      reference_id: existing.phone,
      push_name: existing.pushName,
      connected_at: existing.connectedAt,
      session_id: key,
    });
    return existing;
  }

  if (!force && existing?.sock && existing.status === "pending") {
    emitSession(key, "QR_READY", {
      status: "pending",
      qr_base64: existing.qrBase64,
      message: existing.qrBase64
        ? "Отсканируйте QR-код в WhatsApp → Связанные устройства."
        : "Инициализация WhatsApp сессии…",
      reference_id: null,
      session_id: key,
    });
    return existing;
  }

  if (existing?.reconnectTimer) {
    clearTimeout(existing.reconnectTimer);
  }

  if (existing?.sock) {
    try {
      existing.sock.ev.removeAllListeners();
      existing.sock.end(undefined);
    } catch (_) {
      /* ignore */
    }
  }

  const state = {
    sock: null,
    status: "pending",
    qrBase64: null,
    phone: null,
    pushName: null,
    connectedAt: null,
    starting: true,
    lastQrAt: 0,
    lastQrRaw: null,
    reconnectTimer: null,
    reconnectAttempt: existing?.reconnectAttempt || 0,
  };
  sessions.set(key, state);

  emitSession(key, "QR_READY", {
    status: "pending",
    qr_base64: null,
    message: "Инициализация WhatsApp сессии…",
    reference_id: null,
    session_id: key,
  });

  const authDir = sessionPath(key);
  fs.mkdirSync(authDir, { recursive: true });

  const { state: authState, saveCreds } = await useMultiFileAuthState(authDir);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    auth: {
      creds: authState.creds,
      keys: makeCacheableSignalKeyStore(authState.keys, pino({ level: "silent" })),
    },
    generateHighQualityLinkPreview: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });

  state.sock = sock;
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      const now = Date.now();
      const sameQr = state.lastQrRaw === qr;
      const tooSoon =
        state.lastQrAt > 0 && now - state.lastQrAt < QR_BROADCAST_MIN_INTERVAL_MS;
      if (sameQr || tooSoon) {
        logger.debug(
          { botId: key, sameQr, ageMs: now - state.lastQrAt },
          "Skipping QR broadcast (throttle)",
        );
      } else {
        try {
          const qrBase64 = await qrStringToBase64Png(qr);
          state.qrBase64 = qrBase64;
          state.lastQrAt = now;
          state.lastQrRaw = qr;
          state.status = "pending";
          emitSession(key, "QR_READY", {
            status: "pending",
            qr_base64: qrBase64,
            message: "Отсканируйте QR-код в WhatsApp → Связанные устройства.",
            reference_id: null,
            session_id: key,
          });
        } catch (err) {
          logger.error({ err: err?.message }, "QR encode failed");
          emitSession(key, "AUTH_FAILURE", {
            status: "failed",
            qr_base64: null,
            message: "Не удалось сформировать QR-код.",
            reference_id: null,
            session_id: key,
          });
        }
      }
    }

    if (connection === "open") {
      state.status = "connected";
      state.starting = false;
      state.reconnectAttempt = 0;
      state.phone = jidToPhone(sock.user?.id) || null;
      state.pushName = sock.user?.name || sock.user?.verifiedName || null;
      state.connectedAt = new Date().toISOString();
      broadcast(key, {
        event: "scanning_detected",
        legacy_event: "scanning_detected",
        status: "pending",
        qr_base64: state.qrBase64,
        message: "Сканирование подтверждено…",
        reference_id: state.phone,
        session_id: key,
      });
      emitSession(key, "CONNECTED", {
        status: "connected",
        qr_base64: null,
        message: "WhatsApp успешно подключён.",
        reference_id: state.phone,
        push_name: state.pushName,
        connected_at: state.connectedAt,
        session_id: key,
      });
      logger.info({ botId: key, phone: state.phone }, "WhatsApp session connected");
    }

    if (connection === "close") {
      state.starting = false;
      const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      const badSession =
        statusCode === DisconnectReason.badSession ||
        statusCode === DisconnectReason.multideviceMismatch;
      const wasConnected = state.status === "connected";

      logger.warn(
        { botId: key, statusCode, loggedOut, badSession, wasConnected },
        "WhatsApp connection closed",
      );

      // Clear sock reference so a later startSession can recreate safely.
      if (sessions.get(key)?.sock === sock) {
        state.sock = null;
      }

      if (loggedOut || badSession) {
        state.status = "disconnected";
        emitSession(key, loggedOut ? "DISCONNECTED" : "AUTH_FAILURE", {
          status: "failed",
          qr_base64: null,
          message: loggedOut
            ? "Сессия WhatsApp завершена (logout)."
            : "Ошибка авторизации WhatsApp. Отсканируйте QR заново.",
          reference_id: null,
          session_id: key,
        });
        try {
          fs.rmSync(authDir, { recursive: true, force: true });
        } catch (_) {
          /* ignore */
        }
        sessions.delete(key);
        return;
      }

      // Exponential backoff reconnect — never stack timers.
      if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
      }
      state.reconnectAttempt = (state.reconnectAttempt || 0) + 1;
      const delayMs = backoffDelayMs(state.reconnectAttempt);
      state.status = "pending";
      emitSession(key, "DISCONNECTED", {
        status: "pending",
        qr_base64: state.qrBase64,
        message: `Соединение потеряно. Переподключение через ${Math.round(delayMs / 1000)}с…`,
        reference_id: state.phone,
        session_id: key,
      });
      state.reconnectTimer = setTimeout(() => {
        state.reconnectTimer = null;
        startSession(key, { force: true }).catch((err) =>
          logger.error({ err: err?.message, botId: key }, "reconnect failed"),
        );
      }, delayMs);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const msg of messages) {
      if (!msg.message || msg.key?.fromMe) continue;
      const remoteJid = msg.key?.remoteJid || "";
      if (remoteJid.endsWith("@g.us") || remoteJid === "status@broadcast") continue;
      await forwardInboundToFastAPI(key, msg, msg.pushName);
    }
  });

  state.starting = false;
  return state;
}

async function stopSession(botId) {
  const key = String(botId);
  const existing = sessions.get(key);
  if (existing?.reconnectTimer) {
    clearTimeout(existing.reconnectTimer);
  }
  if (existing?.sock) {
    try {
      await existing.sock.logout();
    } catch (_) {
      try {
        existing.sock.end(undefined);
      } catch (__) {
        /* ignore */
      }
    }
  }
  sessions.delete(key);
  try {
    fs.rmSync(sessionPath(key), { recursive: true, force: true });
  } catch (_) {
    /* ignore */
  }
  emitSession(key, "DISCONNECTED", {
    status: "disconnected",
    qr_base64: null,
    message: "WhatsApp session stopped.",
    reference_id: null,
    session_id: key,
  });
}

async function sendTextMessage(botId, to, text) {
  const key = String(botId);
  const session = sessions.get(key);
  if (!session?.sock || session.status !== "connected") {
    // Attempt to restore from disk if process restarted.
    await startSession(key);
  }
  const live = sessions.get(key);
  if (!live?.sock) {
    throw new Error("WhatsApp session is not connected for this bot.");
  }

  const phone = String(to).replace(/[^\d]/g, "");
  const jid = `${phone}@s.whatsapp.net`;
  await live.sock.sendMessage(jid, { text: String(text).slice(0, 4096) });
  return { ok: true, to: phone };
}

async function sendMediaMessage(botId, to, payload = {}) {
  const key = String(botId);
  const session = sessions.get(key);
  if (!session?.sock || session.status !== "connected") {
    await startSession(key);
  }
  const live = sessions.get(key);
  if (!live?.sock) {
    throw new Error("WhatsApp session is not connected for this bot.");
  }

  const phone = String(to).replace(/[^\d]/g, "");
  const jid = `${phone}@s.whatsapp.net`;
  const mediaUrl = String(payload.media_url || "").trim();
  const mediaType = String(payload.media_type || "document").toLowerCase();
  const caption = payload.caption ? String(payload.caption).slice(0, 1024) : undefined;
  const filename = payload.filename ? String(payload.filename) : undefined;
  const mimeType = payload.mime_type ? String(payload.mime_type) : undefined;

  if (!mediaUrl) {
    throw new Error("media_url is required");
  }

  let content;
  if (mediaType === "image") {
    content = { image: { url: mediaUrl }, caption };
  } else if (mediaType === "video") {
    content = { video: { url: mediaUrl }, caption };
  } else if (mediaType === "audio") {
    content = { audio: { url: mediaUrl }, mimetype: mimeType };
  } else {
    content = {
      document: { url: mediaUrl },
      mimetype: mimeType,
      fileName: filename || "document",
      caption,
    };
  }

  await live.sock.sendMessage(jid, content);
  return { ok: true, to: phone, media_type: mediaType };
}

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));

app.get("/health", (_req, res) => {
  // Public liveness only — never leak session phone numbers / bot ids.
  res.json({
    status: "ok",
    service: "whatsapp-service",
    session_count: sessions.size,
  });
});

app.use("/api", requireInternalAuth);

app.post("/api/sessions/:botId/start", async (req, res) => {
  try {
    const botId = req.params.botId;
    await startSession(botId);
    res.json({ ok: true, bot_id: botId, status: sessions.get(String(botId))?.status });
  } catch (err) {
    logger.error({ err: err?.message }, "start session failed");
    res.status(500).json({ ok: false, error: err?.message || "start_failed" });
  }
});

app.post("/api/sessions/:botId/stop", async (req, res) => {
  try {
    await stopSession(req.params.botId);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ ok: false, error: err?.message || "stop_failed" });
  }
});

app.get("/api/sessions/:botId/status", (req, res) => {
  const session = sessions.get(String(req.params.botId));
  res.json({
    bot_id: req.params.botId,
    status: session?.status || "disconnected",
    phone: session?.phone || null,
    push_name: session?.pushName || null,
    connected_at: session?.connectedAt || null,
    has_qr: Boolean(session?.qrBase64),
  });
});

app.post("/api/sessions/:botId/refresh-qr", async (req, res) => {
  try {
    const botId = req.params.botId;
    const existing = sessions.get(String(botId));
    if (existing?.status === "connected") {
      return res.json({
        ok: true,
        bot_id: botId,
        status: "connected",
        message: "Already connected — QR refresh not needed.",
      });
    }
    await startSession(botId, { force: true });
    res.json({
      ok: true,
      bot_id: botId,
      status: sessions.get(String(botId))?.status || "pending",
    });
  } catch (err) {
    logger.error({ err: err?.message }, "refresh-qr failed");
    res.status(500).json({ ok: false, error: err?.message || "refresh_failed" });
  }
});

app.post("/api/send-message", async (req, res) => {
  try {
    const { bot_id: botId, to, text } = req.body || {};
    if (!botId || !to || !text) {
      return res.status(400).json({ ok: false, error: "bot_id, to and text are required" });
    }
    const result = await sendTextMessage(botId, to, text);
    res.json(result);
  } catch (err) {
    logger.error({ err: err?.message }, "send-message failed");
    res.status(502).json({ ok: false, error: err?.message || "send_failed" });
  }
});

app.post("/api/send-media", async (req, res) => {
  try {
    const body = req.body || {};
    const botId = body.bot_id;
    const to = body.to;
    if (!botId || !to || !body.media_url) {
      return res
        .status(400)
        .json({ ok: false, error: "bot_id, to and media_url are required" });
    }
    const result = await sendMediaMessage(botId, to, body);
    res.json(result);
  } catch (err) {
    logger.error({ err: err?.message }, "send-media failed");
    res.status(502).json({ ok: false, error: err?.message || "send_media_failed" });
  }
});

const server = http.createServer(app);
const wss = new WebSocket.Server({ noServer: true });

function attachQrClient(socket, botId) {
  const key = String(botId);
  if (!qrClients.has(key)) qrClients.set(key, new Set());
  qrClients.get(key).add(socket);
  logger.info({ botId: key }, "QR websocket client connected");

  const existing = sessions.get(key);
  if (existing?.status === "connected") {
    socket.send(
      JSON.stringify({
        event: "CONNECTED",
        legacy_event: "session_connected",
        status: "connected",
        qr_base64: null,
        message: "WhatsApp уже подключён.",
        reference_id: existing.phone,
        push_name: existing.pushName,
        connected_at: existing.connectedAt,
        session_id: key,
      }),
    );
  } else if (existing?.qrBase64) {
    socket.send(
      JSON.stringify({
        event: "QR_READY",
        legacy_event: "qr_code_ready",
        status: "pending",
        qr_base64: existing.qrBase64,
        message: "Отсканируйте QR-код в WhatsApp → Связанные устройства.",
        reference_id: null,
        session_id: key,
      }),
    );
  }

  // Reuse in-memory Baileys session — do NOT force-recreate on client join.
  startSession(key, { force: false }).catch((err) => {
    logger.error({ err: err?.message, botId: key }, "auto-start on WS failed");
    try {
      socket.send(
        JSON.stringify({
          event: "connection_failed",
          status: "failed",
          message: err?.message || "Не удалось запустить WhatsApp сессию.",
          qr_base64: null,
          reference_id: null,
          session_id: key,
        }),
      );
    } catch (_) {
      /* ignore */
    }
  });

  socket.on("message", (raw) => {
    try {
      const data = JSON.parse(String(raw));
      if (data?.type === "ping") {
        socket.send(JSON.stringify({ type: "pong", ts: Date.now() }));
      }
    } catch (_) {
      /* ignore non-JSON */
    }
  });

  // Browser disconnect must NOT destroy the Baileys auth/session.
  socket.on("close", () => {
    qrClients.get(key)?.delete(socket);
    logger.info({ botId: key }, "QR websocket client disconnected (session kept alive)");
  });
}

server.on("upgrade", (request, socket, head) => {
  const pathname = (request.url || "").split("?")[0];
  const match = pathname.match(/^\/ws\/qr\/([^/]+)$/);
  if (!match) {
    socket.destroy();
    return;
  }
  if (!authorizeUpgrade(request)) {
    logger.warn({ path: pathname }, "QR websocket upgrade rejected (auth)");
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
    return;
  }
  const botId = decodeURIComponent(match[1]);
  wss.handleUpgrade(request, socket, head, (ws) => {
    attachQrClient(ws, botId);
  });
});

server.listen(PORT, HOST, () => {
  logger.info({ host: HOST, port: PORT, sessionsDir: SESSIONS_DIR }, "whatsapp-service listening");
});

process.on("SIGINT", () => {
  logger.info("shutting down whatsapp-service");
  server.close(() => process.exit(0));
});
