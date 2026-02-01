(function () {
  "use strict";

  const widget = document.getElementById("chat-widget");
  if (!widget) return;

  if (!window.WebSocket) {
    return;
  }

  // Performance optimization: throttle function
  function throttle(fn, delay) {
    let lastCall = 0;
    let timeoutId = null;
    return function(...args) {
      const now = Date.now();
      const remaining = delay - (now - lastCall);
      if (remaining <= 0) {
        if (timeoutId) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        lastCall = now;
        fn.apply(this, args);
      } else if (!timeoutId) {
        timeoutId = setTimeout(() => {
          lastCall = Date.now();
          timeoutId = null;
          fn.apply(this, args);
        }, remaining);
      }
    };
  }

  const userId = parseInt(widget.dataset.userId || "0", 10);
  const wsPath = widget.dataset.wsPath || "/ws/chat/world/";
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${scheme}://${window.location.host}${wsPath}`;

  const fab = document.getElementById("chat-fab");
  const badge = document.getElementById("chat-fab-badge");
  const panel = document.getElementById("chat-panel");
  const statusEl = document.getElementById("chat-status");
  const messagesEl = document.getElementById("chat-messages");
  const inputEl = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const closeBtn = document.getElementById("chat-close");
  const clearBtn = document.getElementById("chat-clear");
  const headerEl = panel ? panel.querySelector(".chat-header") : null;

  if (!fab || !panel || !messagesEl || !inputEl || !sendBtn || !closeBtn || !clearBtn || !headerEl) return;

  const STORAGE_OPEN_KEY = "chat:world:open";
  const STORAGE_POS_KEY = "chat:world:pos";
  const STORAGE_UNREAD_KEY = "chat:world:unread";
  const MAX_DOM_MESSAGES = 260;
  const MESSAGE_TTL_MS = 15 * 60 * 1000;
  const EDGE_MARGIN_PX = 8;
  const DRAG_THRESHOLD_PX = 6;

  let socket = null;
  let reconnectDelay = 1200;
  let reconnectTimer = null;
  let pingTimer = null;
  let pruneTimer = null;

  let isOpen = false;
  let hasUnread = false;
  let suppressClickUntil = 0;
  let dragState = null;

  const messageIds = new Set();

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function applyWidgetPos(left, top) {
    widget.style.left = `${Math.round(left)}px`;
    widget.style.top = `${Math.round(top)}px`;
    widget.style.right = "auto";
    widget.style.bottom = "auto";
  }

  function ensureWidgetInViewport() {
    if (!widget.style.left || !widget.style.top) return;
    const rect = widget.getBoundingClientRect();
    const nextLeft = clamp(rect.left, EDGE_MARGIN_PX, window.innerWidth - rect.width - EDGE_MARGIN_PX);
    const nextTop = clamp(rect.top, EDGE_MARGIN_PX, window.innerHeight - rect.height - EDGE_MARGIN_PX);
    applyWidgetPos(nextLeft, nextTop);
  }

  function saveWidgetPos() {
    try {
      const rect = widget.getBoundingClientRect();
      const payload = JSON.stringify({ left: Math.round(rect.left), top: Math.round(rect.top) });
      localStorage.setItem(STORAGE_POS_KEY, payload);
    } catch (e) {
      // ignore storage failures
    }
  }

  function loadWidgetPos() {
    try {
      const raw = localStorage.getItem(STORAGE_POS_KEY);
      if (!raw) return;
      const pos = JSON.parse(raw);
      const left = typeof pos.left === "number" ? pos.left : parseFloat(pos.left);
      const top = typeof pos.top === "number" ? pos.top : parseFloat(pos.top);
      if (!Number.isFinite(left) || !Number.isFinite(top)) return;
      applyWidgetPos(left, top);
      ensureWidgetInViewport();
    } catch (e) {
      // ignore
    }
  }

  function setStatus(label, state) {
    if (!statusEl) return;
    statusEl.textContent = label;
    statusEl.classList.remove("is-connected", "is-connecting", "is-disconnected");
    if (state) statusEl.classList.add(`is-${state}`);
  }

  function setUnreadDot(on) {
    hasUnread = !!on;
    if (!badge) return;

    badge.hidden = !hasUnread;

    try {
      localStorage.setItem(STORAGE_UNREAD_KEY, hasUnread ? "1" : "0");
    } catch (e) {
      // ignore storage failures
    }
  }

  function loadUnreadDot() {
    try {
      const raw = localStorage.getItem(STORAGE_UNREAD_KEY);
      if (raw === "1") {
        hasUnread = true;
        badge.hidden = false;
      }
    } catch (e) {
      // ignore
    }
  }

  function setOpen(open) {
    isOpen = !!open;
    panel.classList.toggle("is-open", isOpen);
    panel.setAttribute("aria-hidden", isOpen ? "false" : "true");
    fab.setAttribute("aria-expanded", isOpen ? "true" : "false");

    try {
      localStorage.setItem(STORAGE_OPEN_KEY, isOpen ? "1" : "0");
    } catch (e) {
      // ignore storage failures
    }

    if (isOpen) {
      setUnreadDot(false);
      requestAnimationFrame(() => {
        layoutPanel();
        messagesEl.scrollTop = messagesEl.scrollHeight;
        inputEl.focus();
      });
    }
  }

  function layoutPanel() {
    if (!isOpen) return;

    const margin = EDGE_MARGIN_PX;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const fabRect = fab.getBoundingClientRect();

    panel.style.left = "auto";
    panel.style.right = "0";
    panel.style.top = "auto";
    panel.style.bottom = "66px";

    let rect = panel.getBoundingClientRect();
    const availableAbove = fabRect.top - margin;
    const availableBelow = vh - fabRect.bottom - margin;

    if (rect.top < margin && availableBelow > availableAbove) {
      panel.style.bottom = "auto";
      panel.style.top = "66px";
      rect = panel.getBoundingClientRect();
    }

    if (rect.left < margin) {
      panel.style.right = "auto";
      panel.style.left = "0";
      rect = panel.getBoundingClientRect();
    }

    if (rect.right > vw - margin) {
      panel.style.left = "auto";
      panel.style.right = "0";
    }
  }

  function shouldAutoScroll() {
    const threshold = 90;
    const distance =
      messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
    return distance < threshold;
  }

  function trimDomMessages() {
    while (messagesEl.childElementCount > MAX_DOM_MESSAGES) {
      messagesEl.removeChild(messagesEl.firstElementChild);
    }
  }

  function pruneOldMessages() {
    const cutoff = Date.now() - MESSAGE_TTL_MS;
    const children = Array.from(messagesEl.children);
    for (const el of children) {
      const ts = parseInt(el.dataset.ts || "0", 10);
      if (ts && ts < cutoff) {
        messagesEl.removeChild(el);
      }
    }
  }

  function formatTime(ts) {
    const date = new Date(typeof ts === "number" ? ts : Date.now());
    try {
      return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      const hh = String(date.getHours()).padStart(2, "0");
      const mm = String(date.getMinutes()).padStart(2, "0");
      return `${hh}:${mm}`;
    }
  }

  function appendSystem(text, opts) {
    const shouldScroll = shouldAutoScroll();

    const line = document.createElement("div");
    line.className = "chat-line is-system";
    line.dataset.ts = String(Date.now());
    if (opts && opts.kind === "error") line.classList.add("is-error");

    const bubble = document.createElement("div");
    bubble.className = "chat-system";
    bubble.textContent = text || "";

    line.appendChild(bubble);
    messagesEl.appendChild(line);
    pruneOldMessages();
    trimDomMessages();

    if (shouldScroll) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  function appendMessage(msg, opts) {
    if (!msg || typeof msg !== "object") return;
    if (msg.type !== "message") return;

    const msgId = msg.id != null ? String(msg.id) : "";
    if (msgId) {
      if (messageIds.has(msgId)) return;
      messageIds.add(msgId);
      // Performance optimization: lower threshold for earlier cleanup
      if (messageIds.size > 400) {
        // Best-effort cleanup: drop the entire set when it grows too large.
        messageIds.clear();
        messageIds.add(msgId);
      }
    }

    const shouldScroll = shouldAutoScroll();
    const sender = (msg && msg.sender) || {};
    const senderId = sender && typeof sender.id === "number" ? sender.id : parseInt(sender.id || "0", 10);
    const senderName = sender && sender.name ? String(sender.name) : "玩家";
    const text = msg.text != null ? String(msg.text) : "";
    const isSelf = userId && senderId && userId === senderId;

    // 微信风格气泡布局
    const line = document.createElement("div");
    line.className = "chat-line";
    line.dataset.ts = String(typeof msg.ts === "number" ? msg.ts : Date.now());
    if (isSelf) line.classList.add("is-self");

    const bubbleWrap = document.createElement("div");
    bubbleWrap.className = "chat-bubble-wrap";

    const nameEl = document.createElement("span");
    nameEl.className = "chat-name";
    nameEl.textContent = senderName;

    const bubbleRow = document.createElement("div");
    bubbleRow.className = "chat-bubble-row";

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.textContent = text;

    const timeEl = document.createElement("span");
    timeEl.className = "chat-time";
    timeEl.textContent = formatTime(msg.ts);

    bubbleRow.appendChild(bubble);
    bubbleRow.appendChild(timeEl);

    bubbleWrap.appendChild(nameEl);
    bubbleWrap.appendChild(bubbleRow);

    line.appendChild(bubbleWrap);

    messagesEl.appendChild(line);
    pruneOldMessages();
    trimDomMessages();

    if (shouldScroll) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    const fromHistory = !!(opts && opts.fromHistory);
    if (!isOpen && !isSelf && !fromHistory) {
      setUnreadDot(true);
    }
  }

  function clearMessages() {
    messagesEl.textContent = "";
    messageIds.clear();
  }

  function handlePayload(payload) {
    if (!payload || typeof payload !== "object") return;

    if (payload.type === "history" && Array.isArray(payload.messages)) {
      clearMessages();
      payload.messages.forEach((m) => appendMessage(m, { fromHistory: true }));
      pruneOldMessages();
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return;
    }

    if (payload.type === "status") {
      if (payload.status === "connected") {
        setStatus("已连接", "connected");
      }
      return;
    }

    if (payload.type === "error") {
      appendSystem(payload.message || "发生错误", { kind: "error" });
      return;
    }

    if (payload.type === "message") {
      appendMessage(payload);
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    setStatus("重连中…", "connecting");

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(Math.floor(reconnectDelay * 1.6), 15000);
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }

    setStatus("连接中", "connecting");

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      reconnectDelay = 1200;
      setStatus("已连接", "connected");

      // Keep-alive for some proxies (server accepts ping).
      pingTimer = setInterval(() => {
        try {
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "ping" }));
          }
        } catch (e) {
          // ignore
        }
      }, 25000);
    };

    socket.onmessage = (event) => {
      try {
        handlePayload(JSON.parse(event.data));
      } catch (e) {
        // ignore malformed messages
      }
    };

    socket.onclose = () => {
      setStatus("已断开", "disconnected");
      scheduleReconnect();
    };

    socket.onerror = () => {
      try {
        socket.close();
      } catch (e) {
        // ignore
      }
    };
  }

  function sendCurrent() {
    const raw = inputEl.value || "";
    const text = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
    if (!text) return;

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      appendSystem("未连接到世界频道，正在重连…", { kind: "error" });
      connect();
      return;
    }

    try {
      socket.send(JSON.stringify({ type: "send", text }));
      inputEl.value = "";
      sendBtn.disabled = true;
      inputEl.focus();
    } catch (e) {
      appendSystem("发送失败，请稍后再试", { kind: "error" });
    }
  }

  function updateSendState() {
    sendBtn.disabled = !(inputEl.value || "").trim();
  }

  function startDrag(e, handle) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (dragState) return;

    dragState = {
      pointerId: e.pointerId,
      handle,
      startX: e.clientX,
      startY: e.clientY,
      originRect: widget.getBoundingClientRect(),
      moved: false,
    };

    widget.classList.add("is-dragging");
    try {
      handle.setPointerCapture(e.pointerId);
    } catch (err) {
      // ignore
    }
    window.addEventListener("pointermove", onDragMove, { passive: false });
    window.addEventListener("pointerup", onDragEnd);
    window.addEventListener("pointercancel", onDragEnd);
  }

  function onDragMove(e) {
    if (!dragState || e.pointerId !== dragState.pointerId) return;

    const dx = e.clientX - dragState.startX;
    const dy = e.clientY - dragState.startY;

    if (!dragState.moved) {
      if (Math.abs(dx) < DRAG_THRESHOLD_PX && Math.abs(dy) < DRAG_THRESHOLD_PX) return;
      dragState.moved = true;
      suppressClickUntil = Date.now() + 400;
    }

    e.preventDefault();

    const width = dragState.originRect.width;
    const height = dragState.originRect.height;
    const nextLeft = clamp(dragState.originRect.left + dx, EDGE_MARGIN_PX, window.innerWidth - width - EDGE_MARGIN_PX);
    const nextTop = clamp(dragState.originRect.top + dy, EDGE_MARGIN_PX, window.innerHeight - height - EDGE_MARGIN_PX);

    applyWidgetPos(nextLeft, nextTop);
    layoutPanel();
  }

  function onDragEnd(e) {
    if (!dragState || e.pointerId !== dragState.pointerId) return;

    try {
      dragState.handle.releasePointerCapture(e.pointerId);
    } catch (err) {
      // ignore
    }

    const moved = !!dragState.moved;
    dragState = null;

    widget.classList.remove("is-dragging");
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragEnd);
    window.removeEventListener("pointercancel", onDragEnd);

    if (moved) {
      saveWidgetPos();
      ensureWidgetInViewport();
      layoutPanel();
    }
  }

  fab.addEventListener("pointerdown", (e) => {
    if (isOpen) return;
    startDrag(e, fab);
  });

  headerEl.addEventListener("pointerdown", (e) => {
    if (e.target && e.target.closest && e.target.closest("button")) return;
    startDrag(e, headerEl);
  });

  fab.addEventListener("click", () => {
    if (Date.now() < suppressClickUntil) return;
    setOpen(!isOpen);
  });
  closeBtn.addEventListener("click", () => setOpen(false));
  clearBtn.addEventListener("click", () => {
    clearMessages();
    appendSystem("已清屏");
  });
  sendBtn.addEventListener("click", sendCurrent);

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendCurrent();
    }
  });
  inputEl.addEventListener("input", updateSendState);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen) {
      setOpen(false);
    }
  });

  document.addEventListener("mousedown", (e) => {
    if (!isOpen) return;
    if (e.target && widget.contains(e.target)) return;
    setOpen(false);
  });

  // Performance optimization: throttled resize handler
  window.addEventListener("resize", throttle(() => {
    ensureWidgetInViewport();
    layoutPanel();
  }, 100));

  loadWidgetPos();
  loadUnreadDot();

  try {
    const saved = localStorage.getItem(STORAGE_OPEN_KEY);
    if (saved === "1") {
      setOpen(true);
    } else {
      setOpen(false);
    }
  } catch (e) {
    setOpen(false);
  }

  updateSendState();
  connect();

  pruneTimer = setInterval(pruneOldMessages, 30000);

  window.addEventListener("beforeunload", () => {
    if (pingTimer) clearInterval(pingTimer);
    if (pruneTimer) clearInterval(pruneTimer);
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close();
    }
  });
})();
