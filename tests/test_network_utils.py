from __future__ import annotations

from django.test import RequestFactory, TestCase, override_settings

from core.utils.network import get_client_ip


class NetworkUtilsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_client_ip_without_proxy_returns_remote_addr(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.2"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.8"

        self.assertEqual(get_client_ip(request, trust_proxy=False), "10.0.0.2")

    @override_settings(TRUSTED_PROXY_IPS=["10.0.0.0/24"])
    def test_get_client_ip_uses_xff_for_trusted_proxy(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.2"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.8, 10.0.0.2"

        self.assertEqual(get_client_ip(request, trust_proxy=True), "203.0.113.8")

    @override_settings(TRUSTED_PROXY_IPS=["10.0.0.0/24"])
    def test_get_client_ip_ignores_spoofed_leftmost_xff_hops(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.2"
        request.META["HTTP_X_FORWARDED_FOR"] = "127.0.0.1, 203.0.113.8"

        self.assertEqual(get_client_ip(request, trust_proxy=True), "203.0.113.8")

    @override_settings(TRUSTED_PROXY_IPS=["10.0.0.5"])
    def test_get_client_ip_ignores_xff_for_untrusted_proxy(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.2"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.8"

        self.assertEqual(get_client_ip(request, trust_proxy=True), "10.0.0.2")
