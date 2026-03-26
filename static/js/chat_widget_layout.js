(function (root, factory) {
  const api = factory(root.WorldChatWidgetCore);

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  root.WorldChatWidgetLayout = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (core) {
  "use strict";

  if (!core) {
    throw new Error("WorldChatWidgetCore is required before loading WorldChatWidgetLayout");
  }

  const DEFAULT_EDGE_MARGIN_PX = 8;
  const DEFAULT_DRAG_THRESHOLD_PX = 6;
  const DEFAULT_RESIZE_DELAY_MS = 100;

  function throttle(fn, delay, options) {
    let lastCall = 0;
    let timeoutId = null;
    const setTimeoutFn = options && options.setTimeoutFn ? options.setTimeoutFn : setTimeout;
    const clearTimeoutFn = options && options.clearTimeoutFn ? options.clearTimeoutFn : clearTimeout;

    return function throttled(...args) {
      const now = Date.now();
      const remaining = delay - (now - lastCall);
      if (remaining <= 0) {
        if (timeoutId) {
          clearTimeoutFn(timeoutId);
          timeoutId = null;
        }
        lastCall = now;
        fn.apply(this, args);
        return;
      }

      if (timeoutId) {
        return;
      }

      timeoutId = setTimeoutFn(() => {
        lastCall = Date.now();
        timeoutId = null;
        fn.apply(this, args);
      }, remaining);
    };
  }

  function clampWidgetPosition(rectLike, viewportWidth, viewportHeight, edgeMarginPx) {
    const margin = Number.isFinite(edgeMarginPx) ? edgeMarginPx : DEFAULT_EDGE_MARGIN_PX;
    const width = rectLike && Number.isFinite(rectLike.width) ? rectLike.width : 0;
    const height = rectLike && Number.isFinite(rectLike.height) ? rectLike.height : 0;
    const left = rectLike && Number.isFinite(rectLike.left) ? rectLike.left : 0;
    const top = rectLike && Number.isFinite(rectLike.top) ? rectLike.top : 0;

    return {
      left: core.clamp(left, margin, viewportWidth - width - margin),
      top: core.clamp(top, margin, viewportHeight - height - margin),
    };
  }

  function createLayoutController(config) {
    const widget = config.widget;
    const fab = config.fab;
    const panel = config.panel;
    const windowObj = config.windowObj || window;
    const localStorageLike = config.localStorageLike || localStorage;
    const storagePosKey = config.storagePosKey;
    const getIsOpen = config.getIsOpen;
    const edgeMarginPx = Number.isFinite(config.edgeMarginPx) ? config.edgeMarginPx : DEFAULT_EDGE_MARGIN_PX;
    const dragThresholdPx = Number.isFinite(config.dragThresholdPx)
      ? config.dragThresholdPx
      : DEFAULT_DRAG_THRESHOLD_PX;
    const resizeDelayMs = Number.isFinite(config.resizeDelayMs) ? config.resizeDelayMs : DEFAULT_RESIZE_DELAY_MS;
    const setTimeoutFn = config.setTimeoutFn || setTimeout;
    const clearTimeoutFn = config.clearTimeoutFn || clearTimeout;

    let dragState = null;
    let suppressClickUntil = 0;

    function applyWidgetPos(left, top) {
      widget.style.left = `${Math.round(left)}px`;
      widget.style.top = `${Math.round(top)}px`;
      widget.style.right = "auto";
      widget.style.bottom = "auto";
    }

    function ensureWidgetInViewport() {
      if (!widget.style.left || !widget.style.top) return;
      const rect = widget.getBoundingClientRect();
      const nextPos = clampWidgetPosition(rect, windowObj.innerWidth, windowObj.innerHeight, edgeMarginPx);
      applyWidgetPos(nextPos.left, nextPos.top);
    }

    function saveWidgetPos() {
      try {
        const rect = widget.getBoundingClientRect();
        const payload = core.serializeStoredPosition(rect);
        if (!payload) return;
        localStorageLike.setItem(storagePosKey, payload);
      } catch (_error) {
        // ignore storage failures
      }
    }

    function loadWidgetPos() {
      try {
        const pos = core.parseStoredPosition(localStorageLike.getItem(storagePosKey));
        if (!pos) return;
        applyWidgetPos(pos.left, pos.top);
        ensureWidgetInViewport();
      } catch (_error) {
        // ignore storage failures
      }
    }

    function layoutPanel() {
      if (!getIsOpen()) return;

      const margin = edgeMarginPx;
      const vw = windowObj.innerWidth;
      const vh = windowObj.innerHeight;
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

    function removeDragListeners() {
      windowObj.removeEventListener("pointermove", onDragMove);
      windowObj.removeEventListener("pointerup", onDragEnd);
      windowObj.removeEventListener("pointercancel", onDragEnd);
    }

    function onDragMove(event) {
      if (!dragState || event.pointerId !== dragState.pointerId) return;

      const dx = event.clientX - dragState.startX;
      const dy = event.clientY - dragState.startY;

      if (!dragState.moved) {
        if (Math.abs(dx) < dragThresholdPx && Math.abs(dy) < dragThresholdPx) return;
        dragState.moved = true;
        suppressClickUntil = Date.now() + 400;
      }

      event.preventDefault();

      const width = dragState.originRect.width;
      const height = dragState.originRect.height;
      const nextLeft = core.clamp(
        dragState.originRect.left + dx,
        edgeMarginPx,
        windowObj.innerWidth - width - edgeMarginPx
      );
      const nextTop = core.clamp(
        dragState.originRect.top + dy,
        edgeMarginPx,
        windowObj.innerHeight - height - edgeMarginPx
      );

      applyWidgetPos(nextLeft, nextTop);
      layoutPanel();
    }

    function onDragEnd(event) {
      if (!dragState || event.pointerId !== dragState.pointerId) return;

      try {
        dragState.handle.releasePointerCapture(event.pointerId);
      } catch (_error) {
        // ignore
      }

      const moved = !!dragState.moved;
      dragState = null;

      widget.classList.remove("is-dragging");
      removeDragListeners();

      if (moved) {
        saveWidgetPos();
        ensureWidgetInViewport();
        layoutPanel();
      }
    }

    function handlePointerDown(event, handle) {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (dragState) return;

      dragState = {
        pointerId: event.pointerId,
        handle,
        startX: event.clientX,
        startY: event.clientY,
        originRect: widget.getBoundingClientRect(),
        moved: false,
      };

      widget.classList.add("is-dragging");
      try {
        handle.setPointerCapture(event.pointerId);
      } catch (_error) {
        // ignore
      }

      windowObj.addEventListener("pointermove", onDragMove, { passive: false });
      windowObj.addEventListener("pointerup", onDragEnd);
      windowObj.addEventListener("pointercancel", onDragEnd);
    }

    function shouldSuppressClick(now) {
      const currentTime = Number.isFinite(now) ? now : Date.now();
      return currentTime < suppressClickUntil;
    }

    const onResize = throttle(
      function handleResize() {
        ensureWidgetInViewport();
        layoutPanel();
      },
      resizeDelayMs,
      { setTimeoutFn, clearTimeoutFn }
    );
    windowObj.addEventListener("resize", onResize);

    function teardown() {
      removeDragListeners();
      windowObj.removeEventListener("resize", onResize);
      widget.classList.remove("is-dragging");
      dragState = null;
    }

    return {
      handlePointerDown,
      layoutPanel,
      loadWidgetPos,
      shouldSuppressClick,
      teardown,
    };
  }

  return {
    DEFAULT_DRAG_THRESHOLD_PX,
    DEFAULT_EDGE_MARGIN_PX,
    clampWidgetPosition,
    createLayoutController,
    throttle,
  };
});
