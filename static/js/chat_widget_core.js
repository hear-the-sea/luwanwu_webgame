(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.WorldChatWidgetCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_MAX_MESSAGE_IDS = 400;

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function buildWebSocketUrl(locationLike, wsPath) {
    const path = wsPath || "/ws/chat/world/";
    const protocol = locationLike && locationLike.protocol === "https:" ? "wss" : "ws";
    const host = locationLike && locationLike.host ? String(locationLike.host) : "";
    return `${protocol}://${host}${path}`;
  }

  function normalizeOutgoingText(rawValue) {
    if (rawValue == null) {
      return "";
    }
    return String(rawValue).replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  }

  function parseStoredPosition(rawValue) {
    if (!rawValue) {
      return null;
    }

    let parsed;
    try {
      parsed = typeof rawValue === "string" ? JSON.parse(rawValue) : rawValue;
    } catch (_error) {
      return null;
    }

    const left = typeof parsed.left === "number" ? parsed.left : parseFloat(parsed.left);
    const top = typeof parsed.top === "number" ? parsed.top : parseFloat(parsed.top);
    if (!Number.isFinite(left) || !Number.isFinite(top)) {
      return null;
    }

    return { left, top };
  }

  function serializeStoredPosition(rectLike) {
    const left = rectLike && typeof rectLike.left === "number" ? rectLike.left : parseFloat(rectLike.left);
    const top = rectLike && typeof rectLike.top === "number" ? rectLike.top : parseFloat(rectLike.top);
    if (!Number.isFinite(left) || !Number.isFinite(top)) {
      return null;
    }

    return JSON.stringify({ left: Math.round(left), top: Math.round(top) });
  }

  function nextReconnectDelay(currentDelay) {
    const baseDelay = Number.isFinite(currentDelay) && currentDelay > 0 ? currentDelay : 1200;
    return Math.min(Math.floor(baseDelay * 1.6), 15000);
  }

  function normalizeIncomingMessage(msg, userId) {
    if (!msg || typeof msg !== "object" || msg.type !== "message") {
      return null;
    }

    const sender = msg.sender && typeof msg.sender === "object" ? msg.sender : {};
    const senderIdValue =
      typeof sender.id === "number" ? sender.id : parseInt(sender.id || "0", 10);
    const senderId = Number.isFinite(senderIdValue) ? senderIdValue : 0;
    const normalizedUserId =
      typeof userId === "number" ? userId : parseInt(userId || "0", 10);
    const safeUserId = Number.isFinite(normalizedUserId) ? normalizedUserId : 0;

    return {
      msgId: msg.id != null ? String(msg.id) : "",
      senderId,
      senderName: sender.name ? String(sender.name) : "玩家",
      text: msg.text != null ? String(msg.text) : "",
      timestamp: typeof msg.ts === "number" ? msg.ts : Date.now(),
      isSelf: Boolean(safeUserId && senderId && safeUserId === senderId),
    };
  }

  function shouldResetMessageIds(size, maxSize) {
    const limit = Number.isFinite(maxSize) && maxSize > 0 ? maxSize : DEFAULT_MAX_MESSAGE_IDS;
    return size > limit;
  }

  function shouldMarkUnread(options) {
    return Boolean(options && !options.isOpen && !options.isSelf && !options.fromHistory);
  }

  return {
    DEFAULT_MAX_MESSAGE_IDS,
    buildWebSocketUrl,
    clamp,
    nextReconnectDelay,
    normalizeIncomingMessage,
    normalizeOutgoingText,
    parseStoredPosition,
    serializeStoredPosition,
    shouldMarkUnread,
    shouldResetMessageIds,
  };
});
