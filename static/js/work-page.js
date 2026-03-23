(function () {
  document.querySelectorAll(".recall-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const confirmed =
          window.gameDialog && typeof window.gameDialog.danger === "function"
            ? await window.gameDialog.danger("确定召回吗？召回将不会获得任何报酬。", { title: "召回确认" })
            : window.confirm("确定召回吗？召回将不会获得任何报酬。");
        if (confirmed) {
          form.submit();
        }
      } catch (error) {
        console.error("召回确认失败:", error);
      }
    });
  });
})();
