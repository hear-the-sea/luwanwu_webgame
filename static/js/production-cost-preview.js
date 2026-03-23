(function () {
  function updateTotalCost(input) {
    const targetId = input.dataset.totalTarget || "";
    const totalSpan = targetId ? document.getElementById(targetId) : null;
    if (!totalSpan) {
      return;
    }

    const unitCost = Number.parseInt(input.dataset.unitCost || "", 10);
    const quantity = Number.parseInt(input.value || "", 10) || 1;
    const unitLabel = input.dataset.unitLabel || "";
    const totalCost = (Number.isFinite(unitCost) ? unitCost : 0) * quantity;
    totalSpan.textContent = `总计：${totalCost.toLocaleString()} ${unitLabel}`.trim();
  }

  document.querySelectorAll(".tw-quantity-input[data-total-target]").forEach((input) => {
    input.addEventListener("input", () => updateTotalCost(input));
    input.addEventListener("change", () => updateTotalCost(input));
  });
})();
