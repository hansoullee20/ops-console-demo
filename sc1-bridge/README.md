# SC1-Bridge

SC1-Bridge is the hardware-side companion to the existing attendance workflow in `ops-console-demo`.

## Goal

Replace the manual USB-stick handoff from the K-Media SC-1 attendance terminal with a Raspberry Pi Zero 2 W that presents a controlled USB Mass Storage device to the SC-1, preserves each exported XLS as immutable evidence, and uploads verified copies to the existing attendance system.

## Known device facts

Observed from the actual terminal / prior investigation:

- Product family: K-Media SC-1
- Device model string: `SmartCard_I`
- Fingerprint algorithm: `EASY_A6`
- Firmware: `W806C6_SC1 v2.38`

These facts do **not** establish the filesystem geometry, USB descriptors, power budget, or export-completion behavior. Those remain hardware-test items.

## Safety invariant

> While the SC-1 owns the writable USB medium, Linux must not mount or modify the same backing filesystem as a normal read-write filesystem.

The bridge therefore uses explicit ownership transitions rather than concurrent access.

## Intended flow

```text
SC-1
  │ USB Mass Storage
  ▼
sc1_usb.img
  │ ownership handoff after export completion
  ▼
read-only inspection → SHA-256 → immutable archive → upload queue
  │
  ▼
ops-console-demo attendance API
```

## Current phase

**Hardware Spike 01 — golden USB profile + minimum gadget compatibility test.**

Do not implement unattended production collection until the real SC-1 has successfully written a valid XLS to a Pi-backed virtual USB device.

Start with:

1. `docs/HARDWARE_SPIKE_01.md`
2. `tools/capture_golden_usb_profile.sh`
3. `config/golden-profile.example.json`
4. `docs/ARCHITECTURE.md`
5. `STATUS.md`

## Repository relationship

This directory intentionally lives inside `ops-console-demo` because the server-side SC-1 import, provenance, rollback, and attendance workflows already live here. Hardware code and operational HR data remain separate concerns even though they share one repository.

## Non-goals for the first spike

- no direct modification of SC-1 firmware;
- no direct terminal database access;
- no automatic classification of missing punches as absence;
- no silent overwrite of original XLS exports;
- no assumptions that FAT32, a specific USB size, VID/PID, or bus power will work until measured.
