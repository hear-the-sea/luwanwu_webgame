"""
Custom throttle classes for rate limiting expensive operations.

Usage in views:
    from config.throttling import RecruitThrottle

    @throttle_classes([RecruitThrottle])
    def recruit_view(request):
        ...
"""

from rest_framework.throttling import UserRateThrottle


class RecruitThrottle(UserRateThrottle):
    """Rate limit for guest recruitment operations"""

    scope = "recruit"


class BattleThrottle(UserRateThrottle):
    """Rate limit for battle and mission operations"""

    scope = "battle"


class ClaimThrottle(UserRateThrottle):
    """Rate limit for claiming message attachments"""

    scope = "claim"
