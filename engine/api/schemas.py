from __future__ import annotations

from datetime import date as calendar_date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class StatusResponse(BaseModel):
    camera_available: bool
    wifi_ssid: str | None = None
    disk_free_mb: int = 0
    disk_low: bool = False
    data_degraded: bool = False
    upload_backlog: int = 0
    active_event_id: str | None = None
    admin_pin_set: bool = False
    onboarding_required: bool = False


class AdminUnlockRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class ActiveEventRequest(BaseModel):
    event_id: str | None = None


class PerformanceSettingsRequest(BaseModel):
    device: Literal["pi4", "pi5"]
    mode: Literal["standard", "performance"]
    warning_acknowledged: bool = False

    @model_validator(mode="after")
    def warning_required_for_performance(self):
        if self.mode == "performance" and not self.warning_acknowledged:
            raise ValueError("Acknowledge the cooling and stability warning first")
        return self


class WifiConnectRequest(BaseModel):
    ssid: str = Field(min_length=1)
    password: str | None = None
    hidden: bool = False


class R2SetupRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    access_key: str = Field(min_length=1, max_length=256)
    secret_key: str = Field(min_length=1, max_length=512)
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    public_base_url: HttpUrl
    jurisdiction: Literal["default", "eu", "fedramp"] = "default"


class OnboardingCompleteRequest(BaseModel):
    admin_pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")
    ssh_authorized_key: str = Field(default="", max_length=1000)
    r2: R2SetupRequest

    @field_validator("ssh_authorized_key")
    @classmethod
    def valid_ssh_key(cls, value: str) -> str:
        value = value.strip()
        if value and not value.startswith(("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")):
            raise ValueError("Enter an OpenSSH public key, or leave this blank")
        return value


class EventRequest(BaseModel):
    name: str = Field(min_length=1)
    line1: str = Field(min_length=1)
    line2: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    ends_at: str
    date_separator: Literal[".", "/"] = "/"
    template_id: str

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        calendar_date.fromisoformat(value)
        return value

    @field_validator("ends_at")
    @classmethod
    def valid_ends_at(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.second or parsed.microsecond:
            raise ValueError("End time must be precise to the minute")
        return value

    @model_validator(mode="after")
    def end_not_before_event_date(self):
        if datetime.fromisoformat(self.ends_at).date() < calendar_date.fromisoformat(self.date):
            raise ValueError("End date cannot be before the event date")
        return self

class EventResponse(BaseModel):
    id: str
    name: str
    line1: str
    line2: str
    date: str
    ends_at: str
    launch_until: str
    concluded: bool
    date_separator: Literal[".", "/"] = "/"
    template_id: str
    photo_count: int
    share_url: str | None = None


class EventShareResponse(BaseModel):
    enabled: bool
    url: str | None = None


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    colors: dict[str, str]
    default: bool = False
    print_label: str = "Photo strip"
    strip_width: int = 600
    strip_height: int = 1800
    photo_width: int = 600
    photo_height: int = 400
    custom: bool = False
    archived: bool = False
    event_count: int = 0


class SessionResponse(BaseModel):
    id: str
    event_id: str
    created_at: str
    upload_status: str
    r2_strip_url: str | None
    strip_local_url: str | None = None
    photo_local_urls: list[str] = []


class CaptureResponse(BaseModel):
    photo_index: int
    local_url: str


class WifiNetworkResponse(BaseModel):
    ssid: str
    connected: bool
    signal: int | None = None
