(function (root, factory) {
  const api = factory(root.WorldChatWidgetCore);

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.WorldChatWidgetConnection = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (core) {
  "use strict";

  if (!core) {
    throw new Error("WorldChatWidgetCore is required before loading WorldChatWidgetConnection");
  }

  const DEFAULT_RECONNECT_DELAY_MS = 1200;
  const DEFAULT_PING_INTERVAL_MS = 25000;

  function createConnectionController(config) {
    const wsUrl = config.wsUrl;
    const WebSocketCtor = config.WebSocketCtor;
    const renderer = config.renderer;
    const setStatus = config.setStatus;
    const setTimeoutFn = config.setTimeoutFn || setTimeout;
    const clearTimeoutFn = config.clearTimeoutFn || clearTimeout;
    const setIntervalFn = config.setIntervalFn || setInterval;
    const clearIntervalFn = config.clearIntervalFn || clearInterval;
    const reconnectDelayBase = Number.isFinite(config.reconnectDelayBase)
      ? config.reconnectDelayBase
      : DEFAULT_RECONNECT_DELAY_MS;
    const pingIntervalMs = Number.isFinite(config.pingIntervalMs)
      ? config.pingIntervalMs
      : DEFAULT_PING_INTERVAL_MS;

    let socket = null;
    let reconnectDelay = reconnectDelayBase;
    let reconnectTimer = null;
    let pingTimer = null;
    let disposed = false;

    function clearReconnectTimer() {
      if (!reconnectTimer) return;
      clearTimeoutFn(reconnectTimer);
      reconnectTimer = null;
    }

    function clearPingTimer() {
      if (!pingTimer) return;
      clearIntervalFn(pingTimer);
      pingTimer = null;
    }

    function scheduleReconnect() {
      if (disposed || reconnectTimer) return;
      setStatus("重连中…", "connecting");

      reconnectTimer = setTimeoutFn(() => {
        reconnectTimer = null;
        connect();
      }, reconnectDelay);
      reconnectDelay = core.nextReconnectDelay(reconnectDelay);
    }

    function connect() {
      if (disposed) return;
      if (socket && (socket.readyState === WebSocketCtor.OPEN || socket.readyState === WebSocketCtor.CONNECTING)) {
        return;
      }

      clearReconnectTimer();
      clearPingTimer();
      setStatus("连接中", "connecting");

      socket = new WebSocketCtor(wsUrl);

      socket.onopen = () => {
        reconnectDelay = reconnectDelayBase;
        setStatus("已连接", "connected");
        clearPingTimer();
        pingTimer = setIntervalFn(() => {
          try {
            if (socket && socket.readyState === WebSocketCtor.OPEN) {
              socket.send(JSON.stringify({ type: "ping" }));
            }
          } catch (_error) {
            // ignore
          }
        }, pingIntervalMs);
      };

      socket.onmessage = (event) => {
        try {
          renderer.handlePayload(JSON.parse(event.data), setStatus);
        } catch (_error) {
          // ignore malformed messages
        }
      };

      socket.onclose = () => {
        clearPingTimer();
        setStatus("已断开", "disconnected");
        scheduleReconnect();
      };

      socket.onerror = () => {
        try {
          socket.close();
        } catch (_error) {
          // ignore
        }
      };
    }

    function sendText(text) {
      if (!text) return false;

      if (!socket || socket.readyState !== WebSocketCtor.OPEN) {
        renderer.appendSystem("未连接到世界频道，正在重连…", { kind: "error" });
        connect();
        return false;
      }

      try {
        socket.send(JSON.stringify({ type: "send", text }));
        return true;
      } catch (_error) {
        renderer.appendSystem("发送失败，请稍后再试", { kind: "error" });
        return false;
      }
    }

    function teardown() {
      disposed = true;
      clearReconnectTimer();
      clearPingTimer();

      if (socket && socket.readyState === WebSocketCtor.OPEN) {
        try {
          socket.close();
        } catch (_error) {
          // ignore
        }
      }
    }

    return {
      connect,
      sendText,
      teardown,
    };
  }

  return {
    createConnectionController,
  };
});
