/**
 * 通用工具提示定位模块
 * 用于处理悬浮提示框的位置计算和事件监听
 */
(function() {
    'use strict';

    // 防止重复初始化
    window.__webgame_tooltip = window.__webgame_tooltip || {};

    // Performance optimization: throttle function to limit high-frequency events
    function throttle(fn, delay) {
        let lastCall = 0;
        let timeoutId = null;
        return function(...args) {
            const now = Date.now();
            const remaining = delay - (now - lastCall);
            if (remaining <= 0) {
                if (timeoutId) {
                    clearTimeout(timeoutId);
                    timeoutId = null;
                }
                lastCall = now;
                fn.apply(this, args);
            } else if (!timeoutId) {
                // Schedule trailing call
                timeoutId = setTimeout(() => {
                    lastCall = Date.now();
                    timeoutId = null;
                    fn.apply(this, args);
                }, remaining);
            }
        };
    }

    /**
     * 初始化工具提示
     * @param {Object} options 配置选项
     * @param {string} options.key - 唯一标识符，防止重复初始化
     * @param {string} options.cellSelector - 触发元素选择器 (默认: '.tw-item-cell')
     * @param {string} options.tooltipSelector - 提示框选择器 (默认: '.tw-item-tooltip')
     * @param {number} options.viewportPadding - 视口边距 (默认: 20)
     * @param {number} options.offset - 提示框与触发元素的间距 (默认: 8)
     */
    function initTooltip(options) {
        const config = {
            key: options.key || 'default',
            cellSelector: options.cellSelector || '.tw-item-cell',
            tooltipSelector: options.tooltipSelector || '.tw-item-tooltip',
            viewportPadding: options.viewportPadding || 20,
            offset: options.offset || 8
        };

        // 防止重复初始化
        if (window.__webgame_tooltip[config.key]) return;
        window.__webgame_tooltip[config.key] = true;

        // 检查是否存在目标元素
        if (!document.querySelector(config.cellSelector)) return;

        let activeCell = null;
        let rafId = null;
        let sizeRetryCount = 0;

        function requestUpdate() {
            if (rafId) return;
            rafId = requestAnimationFrame(() => {
                rafId = null;
                if (!activeCell || !activeCell.isConnected) {
                    activeCell = null;
                    sizeRetryCount = 0;
                    return;
                }

                const tooltip = activeCell.querySelector(config.tooltipSelector);
                if (!tooltip) return;

                const cellRect = activeCell.getBoundingClientRect();
                const tooltipRect = tooltip.getBoundingClientRect();

                // 处理尺寸为0的情况（可能是首次渲染）
                if ((tooltipRect.width === 0 || tooltipRect.height === 0) && sizeRetryCount < 2) {
                    sizeRetryCount += 1;
                    rafId = null;
                    requestUpdate();
                    return;
                }
                sizeRetryCount = 0;

                // 计算位置
                let top = cellRect.bottom + config.offset;
                let left = cellRect.left;

                // 防止超出右边界
                if (left + tooltipRect.width > window.innerWidth - config.viewportPadding) {
                    left = window.innerWidth - tooltipRect.width - config.viewportPadding;
                }

                // 防止超出下边界，改为显示在上方
                if (top + tooltipRect.height > window.innerHeight - config.viewportPadding) {
                    top = cellRect.top - tooltipRect.height - config.offset;
                }

                tooltip.style.top = top + 'px';
                tooltip.style.left = left + 'px';
            });
        }

        function setActiveCell(cell) {
            if (activeCell === cell) return;
            activeCell = cell;
            sizeRetryCount = 0;
            requestUpdate();
        }

        // Throttled update for high-frequency events (16ms ≈ 60fps)
        const throttledUpdate = throttle(requestUpdate, 16);

        // 事件监听 - optimized with throttling
        document.addEventListener('mouseover', function(e) {
            const cell = e.target?.closest?.(config.cellSelector);
            if (cell) setActiveCell(cell);
        });

        // Throttled mousemove to reduce CPU usage
        document.addEventListener('mousemove', throttle(function(e) {
            if (activeCell && e.target?.closest?.(config.cellSelector)) {
                requestUpdate();
            }
        }, 32)); // 32ms throttle (~30fps) - sufficient for tooltip positioning

        document.addEventListener('mouseout', function(e) {
            const cell = e.target?.closest?.(config.cellSelector);
            if (cell === activeCell && (!e.relatedTarget || !cell.contains(e.relatedTarget))) {
                activeCell = null;
                sizeRetryCount = 0;
            }
        });

        // Use passive scroll listener for better performance, throttled
        window.addEventListener('scroll', throttle(function() {
            if (activeCell) requestUpdate();
        }, 16), { passive: true });

        // Throttled resize listener
        window.addEventListener('resize', throttle(function() {
            if (activeCell) requestUpdate();
        }, 100));
    }

    // 暴露到全局
    window.initItemTooltip = initTooltip;
})();
