from engine.main import lan_request_allowed


def test_lan_only_exposes_token_protected_phone_surfaces():
    assert lan_request_allowed("127.0.0.1", "/api/events") is True
    assert lan_request_allowed("192.168.1.50", "/studio.html") is True
    assert lan_request_allowed("192.168.1.50", "/api/studio/bootstrap") is True
    assert lan_request_allowed("192.168.1.50", "/assets/piccie-wordmark.svg") is True
    assert lan_request_allowed("192.168.1.50", "/studio.html.evil") is False
    assert lan_request_allowed("192.168.1.50", "/setup.html.evil") is False
    assert lan_request_allowed("192.168.1.50", "/setup.html") is False
    assert lan_request_allowed("192.168.1.50", "/api/setup/status") is False
    assert lan_request_allowed("192.168.1.50", "/api/events") is False
    assert lan_request_allowed("192.168.1.50", "/api/wifi/networks") is False
    assert lan_request_allowed("192.168.1.50", "/api/onboarding/pair") is False
    assert lan_request_allowed("192.168.1.50", "/api/onboarding/complete") is False
    assert lan_request_allowed("192.168.1.50", "/api/d/session-id") is False
    assert lan_request_allowed("192.168.1.50", "/") is False


def _phone_client():
    from fastapi.testclient import TestClient

    from engine.main import app

    return app, TestClient(app, client=("192.168.1.50", 50000))


def test_unpaired_phone_is_refused_before_the_body_is_read(monkeypatch):
    app, phone = _phone_client()
    monkeypatch.setattr(app.state, "template_pairings", {}, raising=False)

    # Invalid JSON: if the body were parsed first, FastAPI would answer 422.
    response = phone.post("/api/studio/templates", content=b"not json")

    assert response.status_code == 401
    assert "no longer active" in response.json()["detail"]


def test_paired_phone_cannot_send_an_oversized_body(monkeypatch):
    app, phone = _phone_client()
    monkeypatch.setattr(app.state, "template_pairings", {"token": True}, raising=False)
    monkeypatch.setattr("engine.main.MAX_STUDIO_BODY_BYTES", 10)

    response = phone.post(
        "/api/studio/templates",
        content=b"x" * 11,
        headers={"X-Studio-Token": "token"},
    )

    assert response.status_code == 413
