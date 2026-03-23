(function () {
  const panel = document.getElementById("arena-registration-panel");
  if (!panel) {
    return;
  }

  const maxSelected = Number.parseInt(panel.dataset.maxSelected || "10", 10);
  const checkboxes = Array.from(document.querySelectorAll(".arena-guest-checkbox"));
  if (!checkboxes.length) {
    return;
  }

  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener("change", async () => {
      const selected = checkboxes.filter((item) => item.checked);
      if (selected.length <= maxSelected) {
        return;
      }

      checkbox.checked = false;
      if (window.gameDialog && typeof window.gameDialog.error === "function") {
        await window.gameDialog.error(`最多只能选择 ${maxSelected} 名门客`);
        return;
      }
      window.alert(`最多只能选择 ${maxSelected} 名门客`);
    });
  });
})();
