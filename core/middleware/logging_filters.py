"""
日志过滤器

为日志记录添加 request_id 信息。
"""

import logging

from .request_id import get_current_request_id


class RequestIDFilter(logging.Filter):
    """
    日志过滤器，为日志记录添加 request_id。

    使用方式：
    1. 在 LOGGING 配置中添加此filter
    2. 在日志formatter中使用 %(request_id)s 占位符
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_current_request_id()  # type: ignore[attr-defined]
        return True


class ExcludeAccessLogFilter(logging.Filter):
    """阻止 access 日志重复经过 root console handler。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name != "access"
