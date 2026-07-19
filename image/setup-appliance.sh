#!/usr/bin/env bash
# Install Piccie engine and kiosk services on a live Pi or pi-gen rootfs.
set -euo pipefail

INSTALL_DIR="/opt/piccie"
DATA_DIR="/data"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

mkdir -p "${DATA_DIR}"
if id pi &>/dev/null; then
  chown pi:pi "${DATA_DIR}"
fi

# --system-site-packages so the venv can see the apt-installed python3-picamera2
# and python3-libcamera (neither is pip-installable).
python3 -m venv --system-site-packages "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

install -m 644 "${INSTALL_DIR}/image/piccie-engine.service" /etc/systemd/system/
install -m 755 "${INSTALL_DIR}/image/kiosk-launch.sh" /usr/local/bin/piccie-kiosk
install -m 755 "${INSTALL_DIR}/image/piccie-update.sh" /usr/local/sbin/piccie-update
install -m 755 "${INSTALL_DIR}/image/piccie-performance" /usr/local/sbin/piccie-performance
install -m 440 "${INSTALL_DIR}/image/files/piccie-performance-sudoers" /etc/sudoers.d/piccie-performance
visudo -cf /etc/sudoers.d/piccie-performance >/dev/null
install -m 644 "${INSTALL_DIR}/image/piccie-bootdiag.service" /etc/systemd/system/
install -m 755 "${INSTALL_DIR}/image/bootdiag.sh" /usr/local/bin/piccie-bootdiag

# Watertight (read-only root + writable /data) units + scripts.
install -m 755 "${INSTALL_DIR}/image/piccie-firstboot-datapart.sh" /usr/local/bin/piccie-firstboot-datapart
install -m 755 "${INSTALL_DIR}/image/piccie-lockdown.sh" /usr/local/bin/piccie-lockdown
install -m 644 "${INSTALL_DIR}/image/piccie-firstboot-datapart.service" /etc/systemd/system/
install -m 644 "${INSTALL_DIR}/image/piccie-lockdown.service" /etc/systemd/system/
install -m 644 "${INSTALL_DIR}/image/data-fallback.service" /etc/systemd/system/

if id pi &>/dev/null; then
  usermod -aG video,netdev pi 2>/dev/null || true
fi

# SSH: key-only. The default OS password on venue WiFi is a root-access hole
# (RPi ships NOPASSWD sudo), and after lockdown `passwd` cannot persist. Disable
# password auth; the operator's key is provisioned to /data/ssh/authorized_keys.
install -d /etc/ssh/sshd_config.d
install -m 644 "${INSTALL_DIR}/image/files/sshd-piccie.conf" /etc/ssh/sshd_config.d/10-piccie.conf

# Baked drop-in configs for read-only root.
install -d /etc/systemd/system.conf.d /etc/systemd/journald.conf.d /etc/NetworkManager/conf.d
install -m 644 "${INSTALL_DIR}/image/files/watchdog.conf" /etc/systemd/system.conf.d/10-watchdog.conf
install -m 644 "${INSTALL_DIR}/image/files/journald-piccie.conf" /etc/systemd/journald.conf.d/10-volatile.conf
install -m 644 "${INSTALL_DIR}/image/files/nm-keyfile-path.conf" /etc/NetworkManager/conf.d/00-piccie-keyfile-path.conf
install -d /etc/polkit-1/rules.d
install -m 644 "${INSTALL_DIR}/image/files/49-piccie-networkmanager.rules" /etc/polkit-1/rules.d/

# Kiosk launches from openbox autostart, which runs INSIDE pi's X session and so
# inherits DISPLAY/XAUTHORITY/XDG_RUNTIME_DIR/HOME. A multi-user.target service
# has none of those and cannot attach to the display. lightdm autologin into the
# openbox X session already works on this image, so we do NOT override the
# session selection (no do_wayland, no custom xsession file).
if id pi &>/dev/null; then
  install -d -o pi -g pi /home/pi/.config/openbox
  install -m 644 -o pi -g pi "${INSTALL_DIR}/image/openbox-autostart" /home/pi/.config/openbox/autostart
  # /home/pi/.config can end up root:root 0700 in the chroot, which blocks pi from
  # reaching the autostart -> the kiosk never launches. Force pi ownership + 0755.
  chown -R pi:pi /home/pi/.config
  chmod 755 /home/pi /home/pi/.config /home/pi/.config/openbox
fi

# cloud-init is unused here (ENABLE_CLOUD_INIT=0) but ships in the base image;
# its failing network stage stalls boot for minutes. Mask it.
systemctl mask cloud-init.service cloud-init-local.service cloud-init-main.service \
  cloud-init-network.service cloud-config.service cloud-final.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable piccie-firstboot-datapart \
  piccie-lockdown data-fallback piccie-engine \
  piccie-bootdiag

echo "Piccie appliance setup complete."
