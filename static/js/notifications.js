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
  let refreshBannerShown = false; // 防止重复显示刷新提示

  // Performance optimization: show a non-intrusive refresh banner instead of auto-reload
  function showRefreshBanner(message) {
    if (refreshBannerShown) return;
    refreshBannerShown = true;

    const banner = document.createElement("div");
    banner.id = "refresh-banner";
    banner.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      background: linear-gradient(135deg, var(--accent-gold, #DAA520), var(--accent-red, #DC143C));
      color: white;
      padding: 10px 20px;
      text-align: center;
      z-index: 10000;
      font-size: 14px;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 15px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    `;

    const textSpan = document.createElement("span");
    textSpan.textContent = message || "页面内容已更新";

    const refreshBtn = document.createElement("button");
    refreshBtn.textContent = "点击刷新";
    refreshBtn.style.cssText = `
      background: white;
      color: var(--accent-red, #DC143C);
      border: none;
      padding: 5px 15px;
      border-radius: 4px;
      cursor: pointer;
      font-weight: bold;
    `;
    refreshBtn.onclick = () => window.location.reload();

    const dismissBtn = document.createElement("button");
    dismissBtn.textContent = "稍后";
    dismissBtn.style.cssText = `
      background: transparent;
      color: white;
      border: 1px solid white;
      padding: 5px 15px;
      border-radius: 4px;
      cursor: pointer;
    `;
    dismissBtn.onclick = () => {
      banner.remove();
      // Allow showing banner again after 30 seconds
      setTimeout(() => { refreshBannerShown = false; }, 30000);
    };

    banner.appendChild(textSpan);
    banner.appendChild(refreshBtn);
    banner.appendChild(dismissBtn);
    document.body.appendChild(banner);
  }

  // Keep legacy function for backward compatibility, but use banner instead
  function scheduleReload(message) {
    showRefreshBanner(message);
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
          (path.includes("/gameplay/") && path.endsWith("/")) ||
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
