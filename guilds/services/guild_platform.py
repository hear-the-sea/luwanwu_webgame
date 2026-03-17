from __future__ import annotations


def bulk_create_messages(*args, **kwargs):
    from gameplay.services.utils.messages import bulk_create_messages as impl

    return impl(*args, **kwargs)


def create_message(*args, **kwargs):
    from gameplay.services.utils.messages import create_message as impl

    return impl(*args, **kwargs)


def spend_resources_locked(*args, **kwargs):
    from gameplay.services.resources import spend_resources_locked as impl

    return impl(*args, **kwargs)
