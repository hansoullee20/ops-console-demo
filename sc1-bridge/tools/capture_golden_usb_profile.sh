#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo ./capture_golden_usb_profile.sh /dev/sdX /dev/sdX1 OUTPUT_DIR

This tool is intentionally read-only with respect to the SC-1 USB device.
It never formats, partitions, repairs, mounts, or writes to the supplied block devices.
EOF
}

if [[ $# -ne 3 ]]; then
  usage >&2
  exit 2
fi

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "ERROR: run with sudo/root so all read-only metadata commands can complete." >&2
  exit 2
fi

DISK=$(readlink -f "$1")
PART=$(readlink -f "$2")
OUT=$3

for dev in "$DISK" "$PART"; do
  if [[ ! -b "$dev" ]]; then
    echo "ERROR: not a block device: $dev" >&2
    exit 2
  fi
done

DISK_TYPE=$(lsblk -dnro TYPE "$DISK" | head -n1)
PART_TYPE=$(lsblk -dnro TYPE "$PART" | head -n1)
if [[ "$DISK_TYPE" != "disk" ]]; then
  echo "ERROR: first argument must be a whole disk; got type '$DISK_TYPE'." >&2
  exit 2
fi
if [[ "$PART_TYPE" != "part" ]]; then
  echo "ERROR: second argument must be a partition; got type '$PART_TYPE'." >&2
  exit 2
fi

PARENT_NAME=$(lsblk -no PKNAME "$PART" | head -n1 | tr -d '[:space:]')
if [[ -z "$PARENT_NAME" || "/dev/$PARENT_NAME" != "$DISK" ]]; then
  echo "ERROR: $PART is not a partition of $DISK." >&2
  exit 2
fi

if findmnt -rn -S "$PART" >/dev/null 2>&1; then
  echo "ERROR: $PART is currently mounted. Unmount it first, then rerun this read-only capture." >&2
  exit 2
fi

mkdir -p "$OUT"

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\n' "$TS" > "$OUT/captured_at_utc.txt"
printf '%s\n' "$DISK" > "$OUT/disk_path.txt"
printf '%s\n' "$PART" > "$OUT/partition_path.txt"

lsblk -b -O "$DISK" > "$OUT/lsblk.txt"
lsblk -b -J -O "$DISK" > "$OUT/lsblk.json"
fdisk -l "$DISK" > "$OUT/fdisk.txt" 2>&1
blkid -p "$DISK" > "$OUT/blkid_disk.txt" 2>&1 || true
blkid -p "$PART" > "$OUT/blkid_partition.txt" 2>&1 || true
udevadm info --query=property --name="$DISK" > "$OUT/udev_disk_properties.txt" 2>&1 || true
udevadm info --query=property --name="$PART" > "$OUT/udev_partition_properties.txt" 2>&1 || true

{
  echo "logical_sector_size=$(blockdev --getss "$DISK")"
  echo "physical_sector_size=$(blockdev --getpbsz "$DISK")"
  echo "device_size_bytes=$(blockdev --getsize64 "$DISK")"
  echo "partition_size_bytes=$(blockdev --getsize64 "$PART")"
} > "$OUT/block_geometry.txt"

# -n means no repair/write. Some non-FAT media will return a controlled error;
# capture it without turning this metadata run into a destructive fallback.
if command -v fsck.fat >/dev/null 2>&1; then
  fsck.fat -vn "$PART" > "$OUT/fsck_fat_readonly.txt" 2>&1 || true
else
  echo "fsck.fat not installed" > "$OUT/fsck_fat_readonly.txt"
fi

cat > "$OUT/README.txt" <<EOF
SC1 golden USB profile capture
captured_at_utc=$TS
disk=$DISK
partition=$PART

The source block devices were inspected only. This script did not mount,
format, partition, repair, or write to them.

Before reproducing a virtual USB image, review all files in this directory
and transfer the confirmed values into config/golden-profile.json.
EOF

echo "Golden profile captured to: $OUT"
