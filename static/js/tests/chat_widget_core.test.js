const test = require("node:test");
const assert = require("node:assert/strict");

const chatWidgetCore = require("../chat_widget_core.js");

test("buildWebSocketUrl respects https and custom paths", () => {
  const url = chatWidgetCore.buildWebSocketUrl(
    { protocol: "https:", host: "example.com" },
    "/ws/chat/world/"
  );

  assert.equal(url, "wss://example.com/ws/chat/world/");
});

test("normalizeOutgoingText trims and normalizes line endings", () => {
  const text = chatWidgetCore.normalizeOutgoingText("  hello\r\nworld \r ");

  assert.equal(text, "hello\nworld");
});

test("parseStoredPosition returns null for invalid payloads", () => {
  assert.equal(chatWidgetCore.parseStoredPosition("not-json"), null);
  assert.equal(chatWidgetCore.parseStoredPosition(JSON.stringify({ left: "x", top: 12 })), null);
});

test("parseStoredPosition parses saved coordinates", () => {
  const parsed = chatWidgetCore.parseStoredPosition(JSON.stringify({ left: "15.2", top: 9 }));

  assert.deepEqual(parsed, { left: 15.2, top: 9 });
});

test("serializeStoredPosition rounds coordinates", () => {
  const serialized = chatWidgetCore.serializeStoredPosition({ left: 10.7, top: 3.2 });

  assert.equal(serialized, JSON.stringify({ left: 11, top: 3 }));
});

test("nextReconnectDelay applies cap and growth", () => {
  assert.equal(chatWidgetCore.nextReconnectDelay(1200), 1920);
  assert.equal(chatWidgetCore.nextReconnectDelay(20000), 15000);
});

test("normalizeIncomingMessage computes sender metadata and self state", () => {
  const message = chatWidgetCore.normalizeIncomingMessage(
    { type: "message", id: 7, sender: { id: "9", name: "来客" }, text: "你好", ts: 1000 },
    9
  );

  assert.deepEqual(message, {
    msgId: "7",
    senderId: 9,
    senderName: "来客",
    text: "你好",
    timestamp: 1000,
    isSelf: true,
  });
});

test("shouldMarkUnread only fires for non-history messages from others when panel is closed", () => {
  assert.equal(
    chatWidgetCore.shouldMarkUnread({ isOpen: false, isSelf: false, fromHistory: false }),
    true
  );
  assert.equal(
    chatWidgetCore.shouldMarkUnread({ isOpen: true, isSelf: false, fromHistory: false }),
    false
  );
  assert.equal(
    chatWidgetCore.shouldMarkUnread({ isOpen: false, isSelf: true, fromHistory: false }),
    false
  );
});
