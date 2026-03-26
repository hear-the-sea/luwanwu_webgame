const test = require("node:test");
const assert = require("node:assert/strict");

global.WorldChatWidgetCore = require("../chat_widget_core.js");
const chatWidgetLayout = require("../chat_widget_layout.js");

test("clampWidgetPosition keeps widget inside viewport bounds", () => {
  const clamped = chatWidgetLayout.clampWidgetPosition(
    { left: -20, top: 500, width: 120, height: 80 },
    320,
    240,
    8
  );

  assert.deepEqual(clamped, { left: 8, top: 152 });
});

test("throttle executes immediately and coalesces delayed calls", () => {
  const calls = [];
  let scheduledCallback = null;

  const throttled = chatWidgetLayout.throttle(
    (value) => calls.push(value),
    100,
    {
      setTimeoutFn(callback) {
        scheduledCallback = callback;
        return 1;
      },
      clearTimeoutFn() {},
    }
  );

  const originalNow = Date.now;
  let fakeNow = 1000;
  Date.now = () => fakeNow;

  try {
    throttled("first");
    fakeNow += 20;
    throttled("second");
    fakeNow += 20;
    throttled("third");

    assert.deepEqual(calls, ["first"]);
    assert.equal(typeof scheduledCallback, "function");

    fakeNow += 80;
    scheduledCallback();

    assert.deepEqual(calls, ["first", "second"]);
  } finally {
    Date.now = originalNow;
  }
});
