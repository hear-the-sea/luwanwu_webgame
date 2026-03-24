from django.contrib.messages import get_messages
from django.urls import reverse


def forge_page_url(*, mode: str = "synthesize", category: str = "all") -> str:
    return f"{reverse('gameplay:forge')}?mode={mode}&category={category}"


def response_messages(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def assert_forge_redirect(response, *, mode: str, category: str) -> None:
    assert response.status_code == 302
    assert response.url == forge_page_url(mode=mode, category=category)
