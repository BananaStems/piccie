from engine.main import lan_request_allowed


def test_lan_only_exposes_paired_studio_surface():
    assert lan_request_allowed("127.0.0.1", "/api/events") is True
    assert lan_request_allowed("192.168.1.50", "/studio.html") is True
    assert lan_request_allowed("192.168.1.50", "/api/studio/bootstrap") is True
    assert lan_request_allowed("192.168.1.50", "/studio.html.evil") is False
    assert lan_request_allowed("192.168.1.50", "/api/events") is False
    assert lan_request_allowed("192.168.1.50", "/api/wifi/networks") is False
