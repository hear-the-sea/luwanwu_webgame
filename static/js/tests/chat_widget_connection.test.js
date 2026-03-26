const test = require("node:test");
const assert = require("node:assert/strict");

global.WorldChatWidgetCore = require("../chat_widget_core.js");
const chatWidgetConnection = require("../chat_widget_connection.js");

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }

  send(payload) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    if (typeof this.onclose === "function") {
      this.onclose();
    }
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    if (typeof this.onopen === "function") {
      this.onopen();
    }
  }

  emitClose() {
    this.readyState = FakeWebSocket.CLOSED;
    if (typeof this.onclose === "function") {
      this.onclose();
    }
  }
}

test("connection controller sends payloads after socket opens", () => {
  FakeWebSocket.instances = [];
  const statuses = [];
  const rendererCalls = [];
  let pingCallback = null;

  const controller = chatWidgetConnection.createConnectionController({
    WebSocketCtor: FakeWebSocket,
    renderer: {
      appendSystem() {
        rendererCalls.push("appendSystem");
      },
      handlePayload() {},
    },
    setStatus(label, state) {
      statuses.push({ label, state });
    },
    setIntervalFn(callback) {
      pingCallback = callback;
      return 1;
    },
    clearIntervalFn() {},
    wsUrl: "ws://example.com/ws/chat/world/",
  });

  controller.connect();
  assert.equal(FakeWebSocket.instances.length, 1);

  const socket = FakeWebSocket.instances[0];
  socket.open();

  const sent = controller.sendText("hello");
  assert.equal(sent, true);
  assert.deepEqual(
    socket.sent.map((entry) => JSON.parse(entry)),
    [{ type: "send", text: "hello" }]
  );

  pingCallback();
  assert.deepEqual(JSON.parse(socket.sent[1]), { type: "ping" });
  assert.deepEqual(statuses.slice(0, 2), [
    { label: "连接中", state: "connecting" },
    { label: "已连接", state: "connected" },
  ]);
  assert.deepEqual(rendererCalls, []);
});

test("connection controller reconnects after close and reports disconnected send attempts", () => {
  FakeWebSocket.instances = [];
  const statuses = [];
  const rendererMessages = [];
  let reconnectCallback = null;

  const controller = chatWidgetConnection.createConnectionController({
    WebSocketCtor: FakeWebSocket,
    renderer: {
      appendSystem(message) {
        rendererMessages.push(message);
      },
      handlePayload() {},
    },
    setStatus(label, state) {
      statuses.push({ label, state });
    },
    setTimeoutFn(callback) {
      reconnectCallback = callback;
      return 1;
    },
    clearTimeoutFn() {},
    setIntervalFn() {
      return 1;
    },
    clearIntervalFn() {},
    wsUrl: "ws://example.com/ws/chat/world/",
  });

  controller.connect();
  const socket = FakeWebSocket.instances[0];
  socket.emitClose();

  assert.equal(typeof reconnectCallback, "function");
  assert.deepEqual(statuses.slice(-2), [
    { label: "已断开", state: "disconnected" },
    { label: "重连中…", state: "connecting" },
  ]);

  const sent = controller.sendText("offline");
  assert.equal(sent, false);
  assert.deepEqual(rendererMessages, ["未连接到世界频道，正在重连…"]);

  reconnectCallback();
  assert.equal(FakeWebSocket.instances.length, 2);
});
