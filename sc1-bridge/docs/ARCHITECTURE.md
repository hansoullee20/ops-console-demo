# SC1-Bridge Architecture

## 1. Boundary

SC1-Bridge owns only the hardware/export boundary:

```text
SC-1 terminal ↔ USB gadget ↔ immutable XLS archive ↔ upload client
```

The existing `ops-console-demo` backend remains authoritative for employee mapping, attendance derivation, leave/replacement operations, exceptions, audit, and month close.

## 2. Storage separation

Recommended Pi layout:

```text
microSD
├── Raspberry Pi OS
├── /var/lib/sc1-bridge/sc1_usb.img
└── /var/lib/sc1-bridge/archive/
    ├── originals/
    ├── manifests/
    └── upload_queue/
```

`sc1_usb.img` is host-facing working media. Archived originals are never exposed back to the SC-1.

## 3. Ownership state machine

```text
READY_FOR_SC1
    ↓
EXPORT_IN_PROGRESS
    ↓ confirmed completion / operator signal
DETACH_FROM_SC1
    ↓
FS_CHECK
    ↓
READ_ONLY_INSPECTION
    ├── discover XLS
    ├── SHA-256
    └── archive original
    ↓
QUEUED_FOR_UPLOAD
    ↓
UPLOADING
    ↓ server acknowledgement + verification
VERIFIED
    ↓
UNMOUNT
    ↓
PRESENT_TO_SC1
    ↓
READY_FOR_SC1
```

For Hardware Spike 01, export completion is manual. Automation based on SCSI eject, cache sync, or an inactivity heuristic is explicitly deferred until USB traffic from the real SC-1 is observed.

## 4. Evidence record

Each archived export should eventually have a manifest equivalent to:

```json
{
  "device_id": "sc1-main",
  "product_model": "SC-1",
  "device_model_string": "SmartCard_I",
  "algorithm_version": "EASY_A6",
  "firmware_version": "W806C6_SC1 v2.38",
  "filename": "...xls",
  "sha256": "...",
  "collected_at": "...",
  "bridge_serial": "...",
  "export_session_id": "..."
}
```

## 5. Failure rules

- Never delete an archived original merely because upload succeeded.
- Never overwrite an archived original with a later export of the same filename.
- Retry upload independently from USB presentation state.
- A failed upload must not block safe re-presentation of the USB medium once the local archive is durable.
- A filesystem integrity failure blocks upload as trusted evidence and must surface as an explicit fault.
- Unknown hardware state must fail closed; do not assume the SC-1 released the medium.

## 6. Hardware target

Initial target: Raspberry Pi Zero 2 W.

Reasons:

- USB device/gadget capability;
- Wi-Fi for upload;
- Linux ConfigFS Mass Storage Gadget support;
- separate power and USB data paths are practical for bench testing.

The SC-1 USB port power budget is unverified. First tests should power the Pi separately from a stable 5 V supply and treat the SC-1 connection primarily as the USB data path until electrical behavior is measured.

## 7. Integration target

The eventual server interface should be an authenticated HTTPS upload endpoint in `ops-console-demo`, carrying the XLS and manifest atomically or under one server-side import session. The existing import pipeline should remain preview/verification oriented; bridge arrival alone must not imply attendance application.
