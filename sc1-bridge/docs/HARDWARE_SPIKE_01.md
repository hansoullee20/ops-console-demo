# Hardware Spike 01 — Golden USB Profile

## Objective

Determine the exact storage profile already accepted by the real SC-1, then reproduce that profile on a Raspberry Pi Zero 2 W USB Mass Storage Gadget.

This spike answers two questions only:

1. Does the SC-1 recognize the Pi as a normal USB storage device?
2. Can the SC-1 create a valid XLS on it?

A successful answer converts the project from architecture research into ordinary embedded-Linux integration work.

## Safety

Use the **actual SC-1 USB stick only in read-only inspection steps** during profile capture. Do not reformat it. Do not run repair mode. Do not mount it read-write.

The helper script intentionally does not call `mkfs`, `dd`, `parted`, `fdisk` write commands, or a read-write mount.

## Step A — capture the golden profile

On a Linux machine, insert the known-good SC-1 USB stick and identify both the whole disk and its data partition.

Example only:

```bash
lsblk -o NAME,PATH,SIZE,TYPE,FSTYPE,FSVER,LABEL,PTTYPE,PARTTYPE,MOUNTPOINTS
```

If the stick is `/dev/sdb` and the data partition is `/dev/sdb1`:

```bash
sudo ./tools/capture_golden_usb_profile.sh /dev/sdb /dev/sdb1 ./golden-profile
```

Review the output before using it to create any virtual disk.

Required observations:

- whole-device capacity;
- partition-table type;
- partition start/end and partition type;
- filesystem type/version;
- volume label and UUID behavior;
- logical/physical sector size;
- FAT geometry where available;
- USB vendor/product/serial descriptors from the known-good stick.

## Step B — build the minimum Pi gadget

Only after Step A is captured, create `sc1_usb.img` to match the known-good geometry as closely as practical.

Do not assume FAT32 or a convenient image size. Those are test outcomes, not inputs.

Use Linux ConfigFS Mass Storage Gadget with one removable LUN. During the first test:

- power the Pi from a separate stable 5 V supply;
- present only the prepared backing image to the SC-1;
- do not mount the backing image locally while presented;
- manually trigger one small SC-1 export;
- wait for the SC-1's normal save-complete UI;
- manually detach the gadget before inspecting the image.

## Step C — inspect the exported image

After detaching from the SC-1:

1. run a non-repairing filesystem check;
2. mount the image read-only;
3. locate the generated XLS;
4. copy the XLS into a separate archive directory;
5. calculate SHA-256;
6. open/parse it with the same parser family used by the attendance importer;
7. compare its structure with an XLS created on the original USB stick under equivalent conditions.

## Pass criteria

Hardware Spike 01 passes only if all of these are true:

- SC-1 recognizes the Pi-backed USB without a terminal reboot;
- SC-1 reports export success through its normal UI;
- the image remains filesystem-consistent after detach;
- at least one XLS is produced;
- the XLS is parseable and structurally equivalent to a normal SC-1 export;
- repeated present/detach does not require reformatting.

## Follow-up matrix

| Test | What it proves | Pass condition |
|---|---|---|
| golden USB profile | exact known-good media geometry | complete captured profile |
| Pi gadget recognition | descriptor/media compatibility | SC-1 sees USB |
| single export | actual write compatibility | valid XLS created |
| repeated export | filename/overwrite behavior | 10/10 intact exports |
| detach/re-present | lifecycle recovery | no SC-1 reboot required |
| reboot matrix | independent recovery | automatic re-recognition |
| power measurement | electrical margin | no brownout/reset |
| forced-power-loss test | corruption behavior | archived originals survive |

## Stop conditions

Stop and diagnose before adding uploader code if:

- SC-1 does not recognize the gadget;
- export appears successful but the filesystem is inconsistent;
- XLS output differs materially from normal USB output;
- the Pi browns out or causes repeated USB resets;
- ownership of the backing image cannot be established unambiguously.

## After this spike

If the test passes, implement in this order:

1. explicit gadget present/detach controller;
2. read-only discovery and immutable archive;
3. SHA-256 manifest;
4. durable upload queue and retry;
5. authenticated server endpoint;
6. operator/status UI;
7. only then investigate safe automatic export-completion detection.
