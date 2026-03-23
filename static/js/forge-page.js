(function () {
  document.querySelectorAll(".js-decompose-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const confirmed =
        window.gameDialog && typeof window.gameDialog.danger === "function"
          ? await window.gameDialog.danger("确认要分解该装备吗？分解后无法恢复。", {
              title: "分解确认",
              okText: "确认分解",
              cancelText: "取消",
            })
          : window.confirm("确认要分解该装备吗？分解后无法恢复。");

      if (confirmed) {
        form.submit();
      }
    });
  });
})();
