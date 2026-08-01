#!/usr/bin/env bash
# First boot only: seed the directories the appliance needs after the early
# piccie-grow-data service has safely expanded and verified the unmounted
# partition/filesystem. /data is then mounted by systemd from fstab before this
# runs (ordered After=data-fallback.service + local-fs.target).
set -euo pipefail

# If /data failed to mount (card too small so p3 was truncated, or the USB/SD
# bridge dropped), data-fallback gave us a tmpfs. Do NOT seed onto RAM or write
# the done-marker there: that would mask the fault, and the marker would vanish
# at power-off anyway. Skip and retry next boot; the engine surfaces the degraded
# state on the admin screen so the operator sees it.
if [ -e /data/.DEGRADED ] || ! mountpoint -q /data; then
  echo "firstboot-datapart: /data is not a real mount (degraded/tmpfs); skipping seed, will retry next boot."
  exit 0
fi

# The /data partition's root dir is root-owned (mkfs default); the engine runs as
# pi and must create /data/events, piccie.db, etc. — so hand /data to pi.
chown pi:pi /data

install -d -m 700 -o root -g root /data/system-connections   # NM keyfiles stay root
install -d -o pi -g pi /data/diag
install -d -o pi -g pi /data/ssh

# Raspberry Pi OS removes image-time SSH host keys so every installation gets a
# unique identity. Generate that identity on persistent /data because the
# appliance root is already read-only when ssh.service starts.
if [ ! -s /data/ssh/ssh_host_ed25519_key ] || [ ! -s /data/ssh/ssh_host_ed25519_key.pub ]; then
  rm -f /data/ssh/ssh_host_ed25519_key /data/ssh/ssh_host_ed25519_key.pub
  ssh-keygen -q -t ed25519 -N '' -f /data/ssh/ssh_host_ed25519_key
fi
chown root:root /data/ssh/ssh_host_ed25519_key /data/ssh/ssh_host_ed25519_key.pub
chmod 600 /data/ssh/ssh_host_ed25519_key
chmod 644 /data/ssh/ssh_host_ed25519_key.pub

# Runtime code lives on /data so updates can be switched atomically while the OS
# and factory copy remain read-only. The image's venv is intentionally shared;
# dependency changes are delivered as appliance images, not live mutations.
install -d -m 755 -o pi -g pi /data/app/releases /data/app/incoming
if [ ! -e /data/app/current ]; then
  install -d -m 755 -o pi -g pi /data/app/releases/factory
  rsync -a --delete \
    /opt/piccie/engine \
    /opt/piccie/web \
    /opt/piccie/templates \
    /opt/piccie/scripts \
    /opt/piccie/requirements.txt \
    /opt/piccie/constraints.txt \
    /opt/piccie/README.md \
    /opt/piccie/VERSION \
    /opt/piccie/BUILD \
    /data/app/releases/factory/
  chown -R pi:pi /data/app
  ln -s /data/app/releases/factory /data/app/current.next
  mv -Tf /data/app/current.next /data/app/current
fi
touch /data/.datapart-done
sync
