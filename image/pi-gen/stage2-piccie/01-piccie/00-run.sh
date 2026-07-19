#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt/piccie"

rsync -a "${BASE_DIR}/piccie-src/" "${ROOTFS_DIR}/opt/piccie/" \
	--exclude data \
	--exclude .git \
	--exclude .pi-gen \
	--exclude deploy \
	--exclude .venv \
	--exclude __pycache__ \
	--exclude config/local.json

install -d "${ROOTFS_DIR}/etc/lightdm/lightdm.conf.d"
install -m 644 "${BASE_DIR}/piccie-src/image/pi-gen/stage2-piccie/files/lightdm/50-piccie.conf" \
	"${ROOTFS_DIR}/etc/lightdm/lightdm.conf.d/50-piccie.conf"

on_chroot <<CHROOT
set -euo pipefail
/opt/piccie/image/setup-appliance.sh

# Camera is enabled in config.txt (camera_auto_detect=0 + dtoverlay=imx708). Do
# NOT call 'raspi-config nonint do_camera' — it rewrites config.txt in the chroot
# and clobbers the explicit overlay / re-enables auto-detect.

# Pin the 7" 1024x600 HDMI panel mode. Under full KMS (vc4-kms-v3d) the legacy
# hdmi_* directives are ignored and a bare 1024x600@60 is REJECTED ("mode not
# supported" — odd horizontal timings). M = CVT timings (even), D = force the
# connector enabled. Plug the screen into HDMI0 (port nearest the USB-C jack).
for CMDLINE in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
	if [ -f "\$CMDLINE" ] && ! grep -q "video=HDMI" "\$CMDLINE"; then
		sed -i 's/\$/ video=HDMI-A-1:1024x600M@60D/' "\$CMDLINE"
	fi
done

# Bake the WiFi regulatory domain (do_wifi_country writes to /etc+/var, which are
# volatile under the read-only overlay, so it must be set at build time).
raspi-config nonint do_wifi_country AU || true

systemctl enable lightdm

# Remove development packages pulled in by the lite base image.
apt-get purge -y --auto-remove \
	git \
	build-essential \
	gdb \
	pkg-config \
	2>/dev/null || true
apt-get autoremove -y
apt-get clean
CHROOT
