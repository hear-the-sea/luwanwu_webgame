(function () {
  const form = document.getElementById("raid-form");
  if (!form) {
    return;
  }

  const raidApiUrl = form.dataset.raidApiUrl || "";
  const mapUrl = form.dataset.mapUrl || "";
  const targetId = Number.parseInt(form.dataset.targetId || "", 10);
  const maxSquadSize = Number.parseInt(form.dataset.maxSquadSize || "0", 10);

  const guestInputs = Array.from(document.querySelectorAll(".guest-input"));
  const troopInputs = Array.from(document.querySelectorAll(".troop-input"));
  const selectedCount = document.getElementById("selected-count");
  const summaryGuests = document.getElementById("summary-guests");
  const summaryTroops = document.getElementById("summary-troops");
  const submitBtn = document.getElementById("submit-btn");

  if (!raidApiUrl || !selectedCount || !summaryGuests || !summaryTroops || !submitBtn || !Number.isFinite(targetId)) {
    return;
  }

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

  function showAlert(message, options) {
    if (typeof window.gameAlert === "function") {
      return window.gameAlert(message, options);
    }
    window.alert(message);
    return Promise.resolve();
  }

  async function showError(message, options) {
    if (window.gameDialog && typeof window.gameDialog.error === "function") {
      return window.gameDialog.error(message, options);
    }
    return showAlert(message, options);
  }

  async function showSuccess(message, options) {
    if (window.gameDialog && typeof window.gameDialog.success === "function") {
      return window.gameDialog.success(message, options);
    }
    return showAlert(message, options);
  }

  function selectedGuestCount() {
    return document.querySelectorAll(".guest-input:checked").length;
  }

  function updateSummary() {
    const selectedGuests = selectedGuestCount();
    selectedCount.textContent = String(selectedGuests);
    summaryGuests.textContent = `${selectedGuests} 人`;

    let totalTroops = 0;
    troopInputs.forEach((input) => {
      totalTroops += Number.parseInt(input.value || "", 10) || 0;
    });
    summaryTroops.textContent = String(totalTroops);
    submitBtn.disabled = selectedGuests === 0;
  }

  guestInputs.forEach((input) => {
    input.addEventListener("change", () => {
      if (selectedGuestCount() > maxSquadSize) {
        input.checked = false;
        showAlert(`最多只能选择 ${maxSquadSize} 名门客出征`, { title: "选择限制" });
        return;
      }
      updateSummary();
    });
  });

  document.querySelectorAll(".btn-adjust").forEach((button) => {
    button.addEventListener("click", () => {
      const troopKey = button.dataset.troop || "";
      const adjust = Number.parseInt(button.dataset.adjust || "0", 10);
      const input = document.querySelector(`[data-troop-key="${troopKey}"]`);
      if (!input) {
        return;
      }

      const max = Number.parseInt(input.dataset.max || "0", 10);
      const currentValue = Number.parseInt(input.value || "", 10) || 0;
      const nextValue = Math.max(0, Math.min(max, currentValue + adjust));
      input.value = String(nextValue);
      updateSummary();
    });
  });

  document.querySelectorAll(".btn-max").forEach((button) => {
    button.addEventListener("click", () => {
      const troopKey = button.dataset.troop || "";
      const input = document.querySelector(`[data-troop-key="${troopKey}"]`);
      if (!input) {
        return;
      }
      input.value = input.dataset.max || "0";
      updateSummary();
    });
  });

  troopInputs.forEach((input) => {
    input.addEventListener("change", () => {
      const max = Number.parseInt(input.dataset.max || "0", 10);
      const value = Number.parseInt(input.value || "", 10) || 0;
      input.value = String(Math.max(0, Math.min(max, value)));
      updateSummary();
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const selectedGuestIds = Array.from(document.querySelectorAll(".guest-input:checked")).map((input) =>
      Number.parseInt(input.value, 10)
    );
    if (!selectedGuestIds.length) {
      await showAlert("请至少选择一名门客出征", { title: "提示" });
      return;
    }

    const troopLoadout = {};
    troopInputs.forEach((input) => {
      const count = Number.parseInt(input.value || "", 10) || 0;
      if (count > 0) {
        troopLoadout[input.dataset.troopKey] = count;
      }
    });

    submitBtn.disabled = true;
    submitBtn.textContent = "发起进攻中...";

    try {
      const response = await fetch(raidApiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({
          target_id: targetId,
          guest_ids: selectedGuestIds,
          troop_loadout: troopLoadout,
        }),
      });
      const data = await response.json();
      if (data.success) {
        await showSuccess(data.message, { title: "出征成功" });
        window.location.href = mapUrl || "/manor/map/";
        return;
      }

      await showError(`出征失败: ${data.error}`, { title: "出征失败" });
    } catch (error) {
      console.error("Raid request failed:", error);
      await showError("请求失败，请稍后重试", { title: "错误" });
    }

    submitBtn.disabled = false;
    submitBtn.textContent = "发起进攻";
  });

  updateSummary();
})();
