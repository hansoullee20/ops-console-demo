# SC1-Bridge Status

Last updated: 2026-08-17 KST

## Current gate

**G0 — Hardware compatibility spike: OPEN**

The project is not yet allowed to claim automatic SC-1 collection.

## Confirmed

- Existing attendance server/import workflow already exists in this repository.
- SC-1 uses USB export to produce Excel/XLS attendance data.
- Raspberry Pi Zero 2 W is the current bridge target.
- Linux USB Mass Storage Gadget is the intended presentation layer.
- Evidence preservation requires explicit host/Pi ownership separation.
- Observed terminal identifiers are documented in `README.md`.

## Not yet confirmed

- filesystem type accepted by this exact SC-1;
- partition geometry and storage-size constraints;
- USB VID/PID/descriptor sensitivity;
- SC-1 USB-port power budget;
- whether the terminal sends a usable SCSI eject/stop signal at export completion;
- whether Pi gadget export produces a byte/structure-valid XLS;
- repeated export behavior and filename overwrite rules.

## Next required evidence

1. Capture the known-good USB profile using `tools/capture_golden_usb_profile.sh`.
2. Commit the reviewed profile as `config/golden-profile.json` on this branch. Do not commit unrelated files from the physical USB.
3. Build a matching `sc1_usb.img` on the Pi.
4. Prove SC-1 recognition and one successful XLS export.
5. Record results before implementing unattended collection or server upload.

## Decision log

### 2026-08-17 — repository placement

Keep SC1-Bridge inside `hansoullee20/ops-console-demo` as a separate top-level module. Reason: the receiving SC-1 import/provenance workflow is already here; a separate repository would add synchronization overhead before the hardware boundary has even passed compatibility testing.

### 2026-08-17 — no assumed FAT profile

Do not hard-code FAT32, capacity, partition table, cluster size, VID/PID, or volume label based on internet examples. Reproduce the known-good physical SC-1 USB profile first.

### 2026-08-17 — manual ownership handoff first

The first working version uses an explicit/manual export-complete handoff. Automatic detection is deferred until real SC-1 USB behavior is measured.
