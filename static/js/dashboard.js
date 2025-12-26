(function () {
  const pad = (num) => String(num).padStart(2, "0");

  function formatCountdown(diffMs, style) {
    if (diffMs <= 0) return style === "zh" || style === "zh-no-sec" ? "已返程" : "完成";
    const totalSeconds = Math.floor(diffMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (style === "zh-no-sec") {
      // 不显示秒，向上取整分钟
      const roundedMinutes = seconds > 0 ? minutes + 1 : minutes;
      const parts = [];
      if (hours > 0) parts.push(`${hours}小时`);
      parts.push(`${roundedMinutes}分钟`);
      return parts.join("");
    }
    if (style === "zh") {
      const parts = [];
      if (hours > 0) parts.push(`${hours}小时`);
      if (hours > 0 || minutes > 0) parts.push(`${minutes}分钟`);
      parts.push(`${seconds}秒`);
      return parts.join("");
    }
    if (hours > 0) {
      return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    }
    return `${pad(minutes)}:${pad(seconds)}`;
  }

  function ensureListPlaceholder(listEl) {
    if (!listEl) return;
    const hasActive = listEl.querySelector(".mission-item:not(.no-mission-placeholder)");
    let placeholder = listEl.querySelector(".no-mission-placeholder");
    if (hasActive) {
      if (placeholder) placeholder.remove();
      return;
    }
    if (!placeholder) {
      placeholder = document.createElement("li");
      placeholder.className = "mission-item no-mission-placeholder muted-text";
      placeholder.textContent = "暂无出征中的门客。";
      listEl.appendChild(placeholder);
    }
  }

  // 获取 CSRF token
  function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const metaToken = meta ? meta.getAttribute("content") : "";
    if (metaToken && metaToken !== "NOTPROVIDED") {
      return metaToken;
    }

    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && input.value) {
      return input.value;
    }

    const cookie = document.cookie
      .split("; ")
      .find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  // 调用检查训练完成的 API 并更新行数据
  async function checkTrainingAndUpdate(el) {
    const checkUrl = el.getAttribute("data-check-url");
    if (!checkUrl) return false;

    const row = el.closest("tr[data-guest-id]");
    if (!row) return false;

    try {
      el.textContent = "检查中...";
      const resp = await fetch(checkUrl, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCSRFToken(),
        },
      });
      const data = await resp.json();
      if (data.success) {
        // 更新等级
        const levelDiv = row.querySelector(".guest-level");
        if (levelDiv) {
          levelDiv.textContent = `Lv ${data.level}`;
        }
        // 更新 HP
        const hpCell = row.querySelectorAll("td")[5]; // 第6列是"生命"列
        if (hpCell) {
          const hpDiv = hpCell.querySelector("div");
          if (hpDiv) {
            hpDiv.textContent = `HP ${data.current_hp}/${data.max_hp}`;
          }
        }
        // 更新训练倒计时
        const upgradeCell = row.querySelectorAll("td")[6]; // 第7列是"升级"列
        if (data.training_eta) {
          el.setAttribute("data-countdown", data.training_eta);
          el.classList.remove("countdown-finished");
          el.textContent = "计算中";
        } else {
          // 已完成，显示"自动升级"
          if (upgradeCell) {
            upgradeCell.innerHTML = '<span class="muted-text">自动升级</span>';
          }
        }
        return true;
      }
    } catch (err) {
      console.error("检查训练状态失败:", err);
    }
    return false;
  }

  function tick() {
    const now = Date.now();
    const ensureEmptyPlaceholder = (removedEl) => {
      if (!removedEl) return;
      const list = removedEl.closest(".mission-list");
      ensureListPlaceholder(list);
    };

    document.querySelectorAll("[data-countdown]").forEach((el) => {
      const targetIso = el.getAttribute("data-countdown");
      if (!targetIso) return;
      const style = el.getAttribute("data-format") || "";
      const shouldRefresh = el.getAttribute("data-refresh") === "1";
      const checkUrl = el.getAttribute("data-check-url");
      const completeText = el.getAttribute("data-complete-text");
      const target = Date.parse(targetIso);
      if (Number.isNaN(target)) return;
      const diff = target - now;
      if (diff <= 0) {
        if (shouldRefresh || checkUrl) {
          el.textContent = "刷新中...";
        } else if (completeText) {
          el.textContent = completeText;
        } else {
          el.textContent = formatCountdown(diff, style);
        }
      } else {
        el.textContent = formatCountdown(diff, style);
      }
      if (diff <= 0) {
        el.classList.add("countdown-finished");
        el.removeAttribute("data-countdown");
        const removeSelector = el.getAttribute("data-remove-selector");
        if (removeSelector) {
          const targetEl = el.closest(removeSelector);
          if (targetEl) {
            targetEl.remove();
            ensureEmptyPlaceholder(targetEl);
          }
        }
        // 优先使用 AJAX 检查（如果配置了 data-check-url）
        if (checkUrl) {
          checkTrainingAndUpdate(el);
        } else if (shouldRefresh) {
          setTimeout(() => window.location.reload(), 500);
        }
      }
    });
    // safety net: ensure all mission lists have placeholder if empty
    document.querySelectorAll(".mission-list").forEach((listEl) => ensureListPlaceholder(listEl));
  }

  document.addEventListener("DOMContentLoaded", () => {
    tick();
    setInterval(tick, 1000);
  });
})();
