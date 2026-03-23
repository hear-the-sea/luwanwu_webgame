(function () {
  const deleteForm = document.getElementById("delete-message-form");
  if (!deleteForm) {
    return;
  }

  deleteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const confirmed =
        window.gameDialog && typeof window.gameDialog.danger === "function"
          ? await window.gameDialog.danger("确认删除这条消息吗？", { title: "删除消息" })
          : window.confirm("确认删除这条消息吗？");
      if (confirmed) {
        deleteForm.submit();
      }
    } catch (error) {
      console.error("删除消息确认失败:", error);
    }
  });
})();
