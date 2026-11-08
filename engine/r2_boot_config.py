"""No-op kept for booths flashed before browser setup.

Their piccie-engine.service still runs ``python -m engine.r2_boot_config`` as
ExecStartPre, and the updater does not replace systemd units, so a missing
module would stop the engine from starting. Delete this file once no booth
runs an image older than the browser-setup release.
"""
