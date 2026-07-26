#!/usr/bin/env python3
"""Run repeated capture-to-guest-download sessions against a Piccie booth."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:8080"


def request(method: str, url: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def request_bytes(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def percentile(values: list[float], percentage: float) -> float:
    """Return a nearest-rank percentile without adding a statistics dependency."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentage + 0.999999) - 1))
    return ordered[index]


def check_status(
    status: dict,
    min_disk_free_mb: int,
    max_upload_backlog: int,
    *,
    require_cloud: bool = True,
) -> None:
    if not status.get("camera_available"):
        raise RuntimeError("Camera unavailable")
    if status.get("data_degraded"):
        raise RuntimeError("Data partition is degraded")
    disk_free = status.get("disk_free_mb")
    if disk_free is not None and disk_free < min_disk_free_mb:
        raise RuntimeError(f"Disk free space fell below {min_disk_free_mb} MB ({disk_free} MB)")
    backlog = status.get("upload_backlog")
    if backlog is not None and backlog > max_upload_backlog:
        raise RuntimeError(f"Upload backlog exceeded {max_upload_backlog} ({backlog})")
    if require_cloud and status.get("r2_reachable") is not True:
        raise RuntimeError(
            "Guest delivery has not been verified: "
            f"{status.get('r2_last_error') or 'readiness check still pending'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Piccie soak test")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--sessions", type=int, default=50)
    parser.add_argument("--event-id", default="")
    parser.add_argument("--pause-seconds", type=float, default=0)
    parser.add_argument("--status-every", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--min-disk-free-mb", type=int, default=500)
    parser.add_argument("--max-upload-backlog", type=int, default=0)
    parser.add_argument("--upload-timeout", type=float, default=120)
    parser.add_argument(
        "--skip-upload-check",
        action="store_true",
        help="Exercise capture/composition only; do not require an R2 guest download.",
    )
    args = parser.parse_args()

    if args.sessions < 1:
        parser.error("--sessions must be at least 1")
    if args.status_every < 1:
        parser.error("--status-every must be at least 1")

    base = args.base.rstrip("/")

    status = request("GET", f"{base}/api/status", timeout=args.timeout)
    check_status(
        status,
        args.min_disk_free_mb,
        args.max_upload_backlog,
        # A stale startup probe may still say offline after Wi-Fi recovered. The
        # first real session below is the authoritative cloud check.
        require_cloud=False,
    )
    print(f"disk_free_mb={status.get('disk_free_mb')} upload_backlog={status.get('upload_backlog')}")

    event_id = args.event_id
    if not event_id:
        events = request("GET", f"{base}/api/events", timeout=args.timeout)
        if not events:
            print("No events found; create one in admin first", file=sys.stderr)
            return 1
        event_id = events[0]["id"]

    latencies: list[float] = []
    for n in range(1, args.sessions + 1):
        t0 = time.perf_counter()
        session = request("POST", f"{base}/api/events/{event_id}/sessions", timeout=args.timeout)
        session_id = session["id"]
        for photo in range(1, 4):
            result = request("POST", f"{base}/api/sessions/{session_id}/capture/{photo}", timeout=args.timeout)
            if not result.get("local_url"):
                raise RuntimeError(f"Session {session_id} photo {photo} returned no local URL")
        final = request("POST", f"{base}/api/sessions/{session_id}/finalize", timeout=args.timeout)
        if not final.get("strip_local_url"):
            raise RuntimeError(f"Session {session_id} returned no composed strip")
        if not args.skip_upload_check:
            deadline = time.monotonic() + args.upload_timeout
            while not final.get("r2_strip_url"):
                if final.get("upload_status") in {"failed", "corrupt"}:
                    raise RuntimeError(
                        f"Session {session_id} upload {final['upload_status']}: "
                        f"{final.get('upload_error') or 'unknown error'}"
                    )
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Session {session_id} did not upload within {args.upload_timeout}s"
                    )
                time.sleep(2)
                final = request(
                    "GET",
                    f"{base}/api/sessions/{session_id}",
                    timeout=args.timeout,
                )
            local_strip = request_bytes(
                f"{base}{final['strip_local_url']}",
                timeout=args.timeout,
            )
            guest_strip = request_bytes(
                final["r2_strip_url"],
                timeout=args.timeout,
            )
            if guest_strip != local_strip:
                raise RuntimeError(
                    f"Session {session_id} guest download did not match its local strip"
                )
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)
        print(f"session {n}/{args.sessions} ok in {elapsed:.2f}s")
        if n % args.status_every == 0 or n == args.sessions:
            status = request("GET", f"{base}/api/status", timeout=args.timeout)
            check_status(
                status,
                args.min_disk_free_mb,
                args.max_upload_backlog,
                require_cloud=not args.skip_upload_check,
            )
            print(
                f"  status disk_free_mb={status.get('disk_free_mb')} "
                f"upload_backlog={status.get('upload_backlog')}"
            )
        if args.pause_seconds and n != args.sessions:
            time.sleep(args.pause_seconds)

    print(
        f"done: {len(latencies)} sessions, avg {statistics.fmean(latencies):.2f}s, "
        f"p50 {percentile(latencies, 0.50):.2f}s, "
        f"p95 {percentile(latencies, 0.95):.2f}s, max {max(latencies):.2f}s"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        print(f"Soak test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
