/**
 * GameDialog - 统一对话框组件
 * 支持 alert, confirm, prompt 三种类型
 * 支持拖动、居中显示
 */
class GameDialog {
  constructor() {
    this.overlay = null;
    this.dialog = null;
    this.isDragging = false;
    this.dragOffset = { x: 0, y: 0 };
    this.resolvePromise = null;
    this.rejectPromise = null;

    // Bind methods
    this._onMouseDown = this._onMouseDown.bind(this);
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseUp = this._onMouseUp.bind(this);
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  /**
   * Create dialog DOM structure
   */
  _createDialogElement(options) {
    const { title, message, showInput, inputValue, buttons } =
      options;

    // Create overlay
    this.overlay = document.createElement("div");
    this.overlay.className = "game-dialog-overlay";
    this.overlay.setAttribute("role", "dialog");
    this.overlay.setAttribute("aria-modal", "true");

    // Create dialog
    this.dialog = document.createElement("div");
    this.dialog.className = "game-dialog";

    // Header
    const header = document.createElement("div");
    header.className = "game-dialog-header";
    header.innerHTML = `
      <h4 class="game-dialog-title">${this._escapeHtml(title)}</h4>
      <button class="game-dialog-close" aria-label="关闭">&times;</button>
    `;

    // Body
    const body = document.createElement("div");
    body.className = "game-dialog-body";
    body.innerHTML = `
      <p class="game-dialog-message">${this._escapeHtml(message)}</p>
      ${showInput ? `<input type="text" class="game-dialog-input" value="${this._escapeHtml(inputValue || "")}" autofocus>` : ""}
    `;

    // Footer with buttons
    const footer = document.createElement("div");
    footer.className = "game-dialog-footer";

    buttons.forEach((btn) => {
      const button = document.createElement("button");
      button.className = `game-dialog-btn game-dialog-btn-${btn.type || "secondary"}`;
      button.textContent = btn.text;
      button.dataset.action = btn.action;
      footer.appendChild(button);
    });

    // Assemble dialog
    this.dialog.appendChild(header);
    this.dialog.appendChild(body);
    this.dialog.appendChild(footer);
    this.overlay.appendChild(this.dialog);

    return this.overlay;
  }

  /**
   * Escape HTML to prevent XSS
   */
  _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Show dialog and return promise
   */
  _show(options) {
    return new Promise((resolve, reject) => {
      this.resolvePromise = resolve;
      this.rejectPromise = reject;

      // Create and append dialog
      const element = this._createDialogElement(options);
      document.body.appendChild(element);

      // Center dialog
      this._centerDialog();

      // Add event listeners
      this._addEventListeners(options);

      // Show with animation (next frame)
      requestAnimationFrame(() => {
        this.overlay.classList.add("visible");

        // Focus input or first button
        const input = this.dialog.querySelector(".game-dialog-input");
        if (input) {
          input.focus();
          input.select();
        } else {
          const firstBtn = this.dialog.querySelector(".game-dialog-btn");
          if (firstBtn) firstBtn.focus();
        }
      });
    });
  }

  /**
   * Center dialog in viewport
   */
  _centerDialog() {
    const rect = this.dialog.getBoundingClientRect();
    const x = (window.innerWidth - rect.width) / 2;
    const y = (window.innerHeight - rect.height) / 2;
    this.dialog.style.left = `${Math.max(0, x)}px`;
    this.dialog.style.top = `${Math.max(0, y)}px`;
  }

  /**
   * Add all event listeners
   */
  _addEventListeners(options) {
    const header = this.dialog.querySelector(".game-dialog-header");
    const closeBtn = this.dialog.querySelector(".game-dialog-close");
    const buttons = this.dialog.querySelectorAll(".game-dialog-btn");

    // Drag events
    header.addEventListener("mousedown", this._onMouseDown);
    header.addEventListener("touchstart", this._onTouchStart.bind(this), {
      passive: false,
    });

    // Close button
    closeBtn.addEventListener("click", () => this._close(null));

    // Action buttons
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        if (action === "confirm") {
          const input = this.dialog.querySelector(".game-dialog-input");
          this._close(input ? input.value : true);
        } else if (action === "cancel") {
          this._close(options.type === "confirm" ? false : null);
        } else if (action === "ok") {
          this._close(true);
        }
      });
    });

    // Overlay click to close (if allowed)
    if (options.closeOnOverlay !== false) {
      this.overlay.addEventListener("click", (e) => {
        if (e.target === this.overlay) {
          this._close(options.type === "confirm" ? false : null);
        }
      });
    }

    // Keyboard
    document.addEventListener("keydown", this._onKeyDown);
  }

  /**
   * Handle keyboard events
   */
  _onKeyDown(e) {
    if (!this.overlay) return;

    if (e.key === "Escape") {
      e.preventDefault();
      this._close(null);
    } else if (e.key === "Enter") {
      const input = this.dialog.querySelector(".game-dialog-input");
      if (input && document.activeElement === input) {
        e.preventDefault();
        this._close(input.value);
      } else if (!input) {
        e.preventDefault();
        const primaryBtn = this.dialog.querySelector(
          ".game-dialog-btn-primary"
        );
        if (primaryBtn) primaryBtn.click();
      }
    }
  }

  /**
   * Mouse down handler for dragging
   */
  _onMouseDown(e) {
    if (e.target.closest(".game-dialog-close")) return;

    this.isDragging = true;
    const rect = this.dialog.getBoundingClientRect();
    this.dragOffset = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };

    this.dialog.querySelector(".game-dialog-header").classList.add("dragging");
    document.body.classList.add("game-dialog-dragging");

    document.addEventListener("mousemove", this._onMouseMove);
    document.addEventListener("mouseup", this._onMouseUp);

    e.preventDefault();
  }

  /**
   * Touch start handler for mobile dragging
   */
  _onTouchStart(e) {
    if (e.target.closest(".game-dialog-close")) return;

    const touch = e.touches[0];
    this.isDragging = true;
    const rect = this.dialog.getBoundingClientRect();
    this.dragOffset = {
      x: touch.clientX - rect.left,
      y: touch.clientY - rect.top,
    };

    this.dialog.querySelector(".game-dialog-header").classList.add("dragging");
    document.body.classList.add("game-dialog-dragging");

    document.addEventListener("touchmove", this._onTouchMove.bind(this), {
      passive: false,
    });
    document.addEventListener("touchend", this._onTouchEnd.bind(this));

    e.preventDefault();
  }

  /**
   * Mouse move handler
   */
  _onMouseMove(e) {
    if (!this.isDragging) return;

    const x = e.clientX - this.dragOffset.x;
    const y = e.clientY - this.dragOffset.y;

    this._setDialogPosition(x, y);
  }

  /**
   * Touch move handler
   */
  _onTouchMove(e) {
    if (!this.isDragging) return;

    const touch = e.touches[0];
    const x = touch.clientX - this.dragOffset.x;
    const y = touch.clientY - this.dragOffset.y;

    this._setDialogPosition(x, y);
    e.preventDefault();
  }

  /**
   * Set dialog position with bounds checking
   */
  _setDialogPosition(x, y) {
    const rect = this.dialog.getBoundingClientRect();
    const maxX = window.innerWidth - rect.width;
    const maxY = window.innerHeight - rect.height;

    // Keep dialog within viewport
    const boundedX = Math.max(0, Math.min(x, maxX));
    const boundedY = Math.max(0, Math.min(y, maxY));

    this.dialog.style.left = `${boundedX}px`;
    this.dialog.style.top = `${boundedY}px`;
  }

  /**
   * Mouse up handler
   */
  _onMouseUp() {
    this._endDrag();
    document.removeEventListener("mousemove", this._onMouseMove);
    document.removeEventListener("mouseup", this._onMouseUp);
  }

  /**
   * Touch end handler
   */
  _onTouchEnd() {
    this._endDrag();
    document.removeEventListener("touchmove", this._onTouchMove);
    document.removeEventListener("touchend", this._onTouchEnd);
  }

  /**
   * End drag operation
   */
  _endDrag() {
    if (!this.isDragging) return;
    this.isDragging = false;

    const header = this.dialog.querySelector(".game-dialog-header");
    if (header) header.classList.remove("dragging");
    document.body.classList.remove("game-dialog-dragging");
  }

  /**
   * Close dialog and resolve promise
   */
  _close(result) {
    if (!this.overlay) return;

    // Remove keyboard listener
    document.removeEventListener("keydown", this._onKeyDown);

    // Hide with animation
    this.overlay.classList.remove("visible");

    // Remove after transition
    setTimeout(() => {
      if (this.overlay && this.overlay.parentNode) {
        this.overlay.parentNode.removeChild(this.overlay);
      }
      this.overlay = null;
      this.dialog = null;

      // Resolve promise
      if (this.resolvePromise) {
        this.resolvePromise(result);
        this.resolvePromise = null;
      }
    }, 200);
  }

  // ========== Public API ==========

  /**
   * Show alert dialog
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<true>}
   */
  alert(message, options = {}) {
    return this._show({
      title: options.title || "提示",
      message,
      type: "info",
      icon: false,
      showInput: false,
      closeOnOverlay: options.closeOnOverlay !== false,
      buttons: [{ text: options.okText || "确定", type: "primary", action: "ok" }],
    });
  }

  /**
   * Show confirm dialog
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<boolean>}
   */
  confirm(message, options = {}) {
    return this._show({
      title: options.title || "确认",
      message,
      type: "confirm",
      icon: false,
      showInput: false,
      closeOnOverlay: options.closeOnOverlay !== false,
      buttons: [
        { text: options.cancelText || "取消", type: "secondary", action: "cancel" },
        {
          text: options.okText || "确定",
          type: options.danger ? "danger" : "primary",
          action: "confirm",
        },
      ],
    });
  }

  /**
   * Show prompt dialog
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<string|null>}
   */
  prompt(message, options = {}) {
    return this._show({
      title: options.title || "请输入",
      message,
      type: "info",
      icon: false,
      showInput: true,
      inputValue: options.defaultValue || "",
      closeOnOverlay: options.closeOnOverlay !== false,
      buttons: [
        { text: options.cancelText || "取消", type: "secondary", action: "cancel" },
        { text: options.okText || "确定", type: "primary", action: "confirm" },
      ],
    });
  }

  /**
   * Show success dialog
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<true>}
   */
  success(message, options = {}) {
    return this.alert(message, { ...options, title: options.title || "成功" });
  }

  /**
   * Show warning dialog
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<true>}
   */
  warning(message, options = {}) {
    return this.alert(message, { ...options, title: options.title || "警告" });
  }

  /**
   * Show error dialog
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<true>}
   */
  error(message, options = {}) {
    return this.alert(message, { ...options, title: options.title || "错误" });
  }

  /**
   * Show danger confirm dialog (red confirm button)
   * @param {string} message - Message to display
   * @param {Object} options - Optional settings
   * @returns {Promise<boolean>}
   */
  danger(message, options = {}) {
    return this.confirm(message, {
      ...options,
      title: options.title || "危险操作",
      danger: true,
    });
  }
}

// Create global instance
window.gameDialog = new GameDialog();

// Convenience functions
window.gameAlert = (message, options) => window.gameDialog.alert(message, options);
window.gameConfirm = (message, options) => window.gameDialog.confirm(message, options);
window.gamePrompt = (message, options) => window.gameDialog.prompt(message, options);
