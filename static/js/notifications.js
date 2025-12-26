(function () {
  // 获取所有消息链接（侧边栏和顶部导航）
  const sidebarLink = document.getElementById("nav-messages-link");
  const topLink = document.getElementById("nav-messages-link-top");
  const messagesLink = sidebarLink || topLink;

  if (!messagesLink) return;

  const toastContainerId = "toast-container";
  const wsPath = "/ws/notifications/";
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${scheme}://${window.location.host}${wsPath}`;

  let socket;
  let reconnectDelay = 2000;
  let currentUnreadCount = parseInt(messagesLink.dataset.unread || "0", 10);
  let reloadScheduled = false; // 防止重复刷新

  function scheduleReload() {
    if (reloadScheduled) return; // 已经计划刷新，不重复触发
    reloadScheduled = true;
    setTimeout(() => window.location.reload(), 1500);
  }

  function updateUnreadCount(increment = 1) {
    currentUnreadCount += increment;

    // 更新侧边栏消息链接文本
    if (sidebarLink) {
      if (currentUnreadCount > 0) {
        sidebarLink.textContent = `消息 (${currentUnreadCount})`;
      } else {
        sidebarLink.textContent = '消息';
      }
    }

    // 更新顶部导航角标
    if (topLink) {
      // 查找现有的角标元素
      let badge = topLink.querySelector("span[style*='position: absolute']");

      if (currentUnreadCount > 0) {
        if (!badge) {
          // 创建新的角标
          badge = document.createElement("span");
          badge.style.cssText = "position: absolute; top: -4px; right: -4px; background: var(--accent-red, #DC143C); color: white; font-size: 10px; padding: 2px 5px; border-radius: 10px; font-weight: bold;";
          topLink.appendChild(badge);
        }
        badge.textContent = currentUnreadCount;
        badge.style.display = "";
      } else if (badge) {
        // 隐藏角标
        badge.style.display = "none";
      }
    }

    // 更新 data-unread 属性
    if (sidebarLink) sidebarLink.dataset.unread = currentUnreadCount;
    if (topLink) topLink.dataset.unread = currentUnreadCount;
  }

  function showToast({ title, body, kind }) {
    const container = document.getElementById(toastContainerId);
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${kind || "system"}`;
    const titleEl = document.createElement("div");
    titleEl.className = "toast-title";
    titleEl.textContent = title || "新通知";
    const bodyEl = document.createElement("div");
    bodyEl.className = "toast-body";
    bodyEl.textContent = body || "";
    toast.appendChild(titleEl);
    toast.appendChild(bodyEl);
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 300);
    }, 5000);
  }

  function handlePayload(payload) {
    if (!payload) return;
    if (payload.kind === "system" && payload.building_key) {
      updateUnreadCount(1);
      showToast({
        title: payload.title || "建筑升级完成",
        body: `当前等级 Lv${payload.level || "?"}`,
        kind: "system",
      });
      // 如果在庄园页面，自动刷新
      if (window.location.pathname.includes("/gameplay/") || window.location.pathname === "/") {
        scheduleReload();
      }
      return;
    }
    if (payload.kind === "system" && payload.tech_key) {
      updateUnreadCount(1);
      showToast({
        title: payload.title || "技术研究完成",
        body: `当前等级 Lv${payload.level || "?"}`,
        kind: "system",
      });
      // 如果在技术页面，自动刷新
      if (window.location.pathname.includes("/technology")) {
        scheduleReload();
      }
      return;
    }
    if (payload.kind === "battle") {
      updateUnreadCount(1);
      const missionLabel = payload.mission_name || payload.title || payload.mission_key || "";
      showToast({
        title: payload.title || "战报更新",
        body: missionLabel ? `${missionLabel} 已完成` : "战斗结果已生成",
        kind: "battle",
      });
      // 如果在相关页面，自动刷新以显示更新的任务列表和门客状态
      const path = window.location.pathname;
      if (path.includes("/gameplay/tasks") ||
          path.includes("/gameplay/") && path.endsWith("/") ||
          path.includes("/guests/roster")) {
        scheduleReload();
      }
      return;
    }
    updateUnreadCount(1);
    showToast({ title: payload.title || "新消息", body: payload.body || "", kind: "system" });
  }

  function connect() {
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      reconnectDelay = 2000;
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handlePayload(payload);
      } catch (e) {
        // ignore malformed messages
      }
    };

    socket.onclose = () => {
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  document.addEventListener("DOMContentLoaded", () => {
    // 连接 WebSocket
    connect();
  });
})();
