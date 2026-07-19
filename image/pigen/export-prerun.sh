#!/bin/bash -e
# piccie override of pi-gen export-image/prerun.sh.
# Adds a THIRD partition (p3 = /data) at build time so the appliance can run a
# read-only root + writable /data. Root is kept fixed-size; the `resize` cmdline
# token is removed (see image/pigen/cmdline.txt) so root does NOT grow to fill
# the disk and leave no room for p3. p3 is grown to fill the device on first
# boot (x-systemd.growfs + piccie-firstboot-datapart).

IMG_FILE="${STAGE_WORK_DIR}/${IMG_FILENAME}${IMG_SUFFIX}.img"

unmount_image "${IMG_FILE}"

rm -f "${IMG_FILE}"

rm -rf "${ROOTFS_DIR}"
mkdir -p "${ROOTFS_DIR}"

BOOT_SIZE="$((512 * 1024 * 1024))"
ROOT_SIZE=$(du -x --apparent-size -s "${EXPORT_ROOTFS_DIR}" --exclude var/cache/apt/archives --exclude boot/firmware --block-size=1 | cut -f 1)

# All partition sizes and starts will be aligned to this size
ALIGN="$((8 * 1024 * 1024))"
ROOT_MARGIN="$(echo "($ROOT_SIZE * 0.2 + 200 * 1024 * 1024) / 1" | bc)"

# Dedicated /data partition, FIXED size (no runtime grow — a runtime resize races
# systemd growfs and deadlocks boot). 8 GiB holds ~hundreds of sessions. Keeping
# root fixed means root is always clean (read-only).
DATA_SIZE="$((8 * 1024 * 1024 * 1024))"

BOOT_PART_START=$((ALIGN))
BOOT_PART_SIZE=$(((BOOT_SIZE + ALIGN - 1) / ALIGN * ALIGN))
ROOT_PART_START=$((BOOT_PART_START + BOOT_PART_SIZE))
ROOT_PART_SIZE=$(((ROOT_SIZE + ROOT_MARGIN + ALIGN - 1) / ALIGN * ALIGN))
DATA_PART_START=$((ROOT_PART_START + ROOT_PART_SIZE))
DATA_PART_SIZE=$(((DATA_SIZE + ALIGN - 1) / ALIGN * ALIGN))
IMG_SIZE=$((DATA_PART_START + DATA_PART_SIZE))

truncate -s "${IMG_SIZE}" "${IMG_FILE}"

parted --script "${IMG_FILE}" mklabel msdos
parted --script "${IMG_FILE}" unit B mkpart primary fat32 "${BOOT_PART_START}" "$((BOOT_PART_START + BOOT_PART_SIZE - 1))"
parted --script "${IMG_FILE}" unit B mkpart primary ext4 "${ROOT_PART_START}" "$((ROOT_PART_START + ROOT_PART_SIZE - 1))"
parted --script "${IMG_FILE}" unit B mkpart primary ext4 "${DATA_PART_START}" "$((DATA_PART_START + DATA_PART_SIZE - 1))"

echo "Creating loop device..."
cnt=0
until ensure_next_loopdev && LOOP_DEV="$(losetup --show --find --partscan "$IMG_FILE")"; do
	if [ $cnt -lt 5 ]; then
		cnt=$((cnt + 1))
		echo "Error in losetup.  Retrying..."
		sleep 5
	else
		echo "ERROR: losetup failed; exiting"
		exit 1
	fi
done

ensure_loopdev_partitions "$LOOP_DEV"
BOOT_DEV="${LOOP_DEV}p1"
ROOT_DEV="${LOOP_DEV}p2"
DATA_DEV="${LOOP_DEV}p3"

ROOT_FEATURES="^huge_file"
for FEATURE in 64bit; do
if grep -q "$FEATURE" /etc/mke2fs.conf; then
	ROOT_FEATURES="^$FEATURE,$ROOT_FEATURES"
fi
done

if [ "$BOOT_SIZE" -lt 134742016 ]; then
	FAT_SIZE=16
else
	FAT_SIZE=32
fi

mkdosfs -n bootfs -F "$FAT_SIZE" -s 1 -v "$BOOT_DEV" > /dev/null
mkfs.ext4 -L rootfs -O "$ROOT_FEATURES" "$ROOT_DEV" > /dev/null
mkfs.ext4 -L data -E lazy_itable_init=0,lazy_journal_init=0 "$DATA_DEV" > /dev/null
tune2fs -c 30 -i 2w "$DATA_DEV" > /dev/null    # periodic full fsck guard (flaky bridge)

mount -v "$ROOT_DEV" "${ROOTFS_DIR}" -t ext4
mkdir -p "${ROOTFS_DIR}/boot/firmware"
mount -v "$BOOT_DEV" "${ROOTFS_DIR}/boot/firmware" -t vfat

rsync -aHAXx --exclude /var/cache/apt/archives --exclude /boot/firmware "${EXPORT_ROOTFS_DIR}/" "${ROOTFS_DIR}/"
rsync -rtx "${EXPORT_ROOTFS_DIR}/boot/firmware/" "${ROOTFS_DIR}/boot/firmware/"
