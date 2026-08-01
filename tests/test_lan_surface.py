from engine.main import lan_request_allowed


def test_lan_only_exposes_token_protected_phone_surfaces():
    assert lan_request_allowed("127.0.0.1", "/api/events") is True
    assert lan_request_allowed("192.168.1.50", "/studio.html") is True
    assert lan_request_allowed("192.168.1.50", "/api/studio/bootstrap") is True
    assert lan_request_allowed("192.168.1.50", "/api/d/session-id") is True
    assert lan_request_allowed("192.168.1.50", "/assets/piccie-wordmark.svg") is True
    assert lan_request_allowed("192.168.1.50", "/studio.html.evil") is False
    assert lan_request_allowed("192.168.1.50", "/setup.html.evil") is False
    assert lan_request_allowed("192.168.1.50", "/setup.html") is False
    assert lan_request_allowed("192.168.1.50", "/api/setup/status") is False
    assert lan_request_allowed("192.168.1.50", "/api/events") is False
    assert lan_request_allowed("192.168.1.50", "/api/wifi/networks") is False
    assert lan_request_allowed("192.168.1.50", "/api/onboarding/pair") is False
    assert lan_request_allowed("192.168.1.50", "/api/onboarding/complete") is False
    assert lan_request_allowed("192.168.1.50", "/") is False
