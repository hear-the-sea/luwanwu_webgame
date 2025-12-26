/**
 * Real-time online user statistics via WebSocket
 */

(function() {
    'use strict';

    // 检查是否支持 WebSocket
    if (!window.WebSocket) {
        console.error('WebSocket is not supported by this browser');
        return;
    }

    // 构建 WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/online-stats/`;

    let ws = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;
    const reconnectDelay = 3000; // 3秒

    function connectWebSocket() {
        try {
            ws = new WebSocket(wsUrl);

            ws.onopen = function(event) {
                console.log('在线统计 WebSocket 已连接');
                reconnectAttempts = 0;
            };

            ws.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    updateOnlineStats(data);
                } catch (error) {
                    console.error('解析在线统计数据失败:', error);
                }
            };

            ws.onerror = function(error) {
                console.error('WebSocket 错误:', error);
            };

            ws.onclose = function(event) {
                console.log('在线统计 WebSocket 已断开');

                // 尝试重连
                if (reconnectAttempts < maxReconnectAttempts) {
                    reconnectAttempts++;
                    console.log(`尝试重连 (${reconnectAttempts}/${maxReconnectAttempts})...`);
                    setTimeout(connectWebSocket, reconnectDelay);
                } else {
                    console.error('达到最大重连次数，放弃重连');
                }
            };
        } catch (error) {
            console.error('创建 WebSocket 连接失败:', error);
        }
    }

    function updateOnlineStats(data) {
        const onlineCountElement = document.getElementById('online-user-count');
        const totalCountElement = document.getElementById('total-user-count');

        if (onlineCountElement && data.online_count !== undefined) {
            onlineCountElement.textContent = data.online_count;
        }

        if (totalCountElement && data.total_count !== undefined) {
            totalCountElement.textContent = data.total_count;
        }
    }

    // 页面加载完成后连接 WebSocket
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connectWebSocket);
    } else {
        connectWebSocket();
    }

    // 页面卸载时关闭连接
    window.addEventListener('beforeunload', function() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.close();
        }
    });
})();
