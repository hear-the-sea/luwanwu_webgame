"""
Compatibility entrypoint for trade selector tests.

The original file exceeded the audit size threshold. Tests now live in
`tests/trade_selectors/` submodules while this path remains stable for
existing pytest commands and CI references.
"""

from tests.trade_selectors.auction_context import *  # noqa: F401,F403
from tests.trade_selectors.bank_context import *  # noqa: F401,F403
from tests.trade_selectors.market_context import *  # noqa: F401,F403
from tests.trade_selectors.shop_context import *  # noqa: F401,F403
