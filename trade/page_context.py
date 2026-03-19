from __future__ import annotations

import logging
from typing import Any

from django.http import HttpRequest

from gameplay.services.manor.core import get_manor
from gameplay.services.resources import project_resource_production_for_read
from gameplay.views.read_helpers import prepare_manor_for_read
from trade.selectors import get_trade_context

logger = logging.getLogger(__name__)


def build_trade_page_context(request: HttpRequest) -> dict[str, Any]:
    """Assemble the trade page read model for the current authenticated user."""
    manor = get_manor(request.user)
    prepare_manor_for_read(
        manor,
        project_fn=project_resource_production_for_read,
        logger=logger,
        source="trade_view",
        user_id=getattr(request.user, "id", None),
    )
    return get_trade_context(request, manor)
