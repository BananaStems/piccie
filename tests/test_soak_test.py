from scripts.soak_test import check_status, percentile


def test_percentile_uses_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert percentile(values, 0.50) == 3.0
    assert percentile(values, 0.95) == 5.0


def test_status_limits_fail_closed() -> None:
    healthy = {
        "camera_available": True,
        "data_degraded": False,
        "disk_free_mb": 1000,
        "upload_backlog": 2,
    }

    check_status(healthy, min_disk_free_mb=500, max_upload_backlog=10)

    unhealthy = {**healthy, "upload_backlog": 11}
    try:
        check_status(unhealthy, min_disk_free_mb=500, max_upload_backlog=10)
    except RuntimeError as exc:
        assert "Upload backlog" in str(exc)
    else:
        raise AssertionError("backlog limit should fail the soak test")
