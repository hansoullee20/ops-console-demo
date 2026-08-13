#!/usr/bin/env python3
"""Privacy-safe Fold4 evidence collector for Okja target-device gates.

Collects device/app/resource metadata through adb without persisting transcripts or
raw microphone audio. The existing wake_diagnostic_events.jsonl may be pulled at
session end for G2.8 latency analysis.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

PACKAGE = "com.soul.aihub"


class CollectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResourceSample:
    captured_at_utc: str
    device_uptime_s: float | None
    pid: int | None
    cpu_pct: float | None
    pss_kb: int | None
    java_heap_kb: int | None
    native_heap_kb: int | None
    thermal_status: str | None
    battery_level_pct: int | None
    battery_temperature_c: float | None


def run_command(argv: list[str], check: bool = True) -> str:
    proc = subprocess.run(argv, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise CollectorError(
            f"command failed ({proc.returncode}): {' '.join(argv)}\n{proc.stderr.strip()}"
        )
    return proc.stdout


def adb_args(serial: str | None, *args: str) -> list[str]:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return cmd


def parse_first_float(text: str) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def parse_meminfo(text: str) -> dict[str, int | None]:
    total = re.search(r"TOTAL\s+(\d+)", text)
    java = re.search(r"Java Heap:\s*(\d+)", text)
    native = re.search(r"Native Heap:\s*(\d+)", text)
    return {
        "pss_kb": int(total.group(1)) if total else None,
        "java_heap_kb": int(java.group(1)) if java else None,
        "native_heap_kb": int(native.group(1)) if native else None,
    }


def parse_top_cpu(text: str, package: str = PACKAGE) -> tuple[int | None, float | None]:
    for line in text.splitlines():
        if package not in line:
            continue
        parts = line.split()
        pid = int(parts[0]) if parts and parts[0].isdigit() else None
        pct = None
        for token in parts[1:]:
            if token.endswith("%"):
                try:
                    pct = float(token[:-1])
                    break
                except ValueError:
                    pass
        if pct is None:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
            pct = float(m.group(1)) if m else None
        return pid, pct
    return None, None


def parse_battery(text: str) -> tuple[int | None, float | None]:
    level = re.search(r"level:\s*(\d+)", text)
    temp = re.search(r"temperature:\s*(\d+)", text)
    return (
        int(level.group(1)) if level else None,
        int(temp.group(1)) / 10.0 if temp else None,
    )


def parse_thermal(text: str) -> str | None:
    for line in text.splitlines():
        if "status" in line.lower():
            value = line.split(":", 1)[-1].strip()
            if value:
                return value
    stripped = text.strip()
    return stripped[:200] if stripped else None


def get_prop(serial: str | None, key: str) -> str:
    return run_command(adb_args(serial, "shell", "getprop", key)).strip()


def capture_sample(serial: str | None, package: str) -> ResourceSample:
    uptime_text = run_command(adb_args(serial, "shell", "cat", "/proc/uptime"), check=False)
    uptime = parse_first_float(uptime_text)
    top_text = run_command(adb_args(serial, "shell", "top", "-b", "-n", "1"), check=False)
    pid, cpu = parse_top_cpu(top_text, package)
    mem_text = run_command(adb_args(serial, "shell", "dumpsys", "meminfo", package), check=False)
    mem = parse_meminfo(mem_text)
    thermal_text = run_command(adb_args(serial, "shell", "dumpsys", "thermalservice"), check=False)
    battery_text = run_command(adb_args(serial, "shell", "dumpsys", "battery"), check=False)
    battery_level, battery_temp = parse_battery(battery_text)
    return ResourceSample(
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
        device_uptime_s=uptime,
        pid=pid,
        cpu_pct=cpu,
        pss_kb=mem["pss_kb"],
        java_heap_kb=mem["java_heap_kb"],
        native_heap_kb=mem["native_heap_kb"],
        thermal_status=parse_thermal(thermal_text),
        battery_level_pct=battery_level,
        battery_temperature_c=battery_temp,
    )


def device_metadata(serial: str | None, package: str) -> dict[str, object]:
    devices = run_command(["adb", "devices"]).strip().splitlines()[1:]
    online = [line.split()[0] for line in devices if line.strip().endswith("\tdevice")]
    if serial:
        if serial not in online:
            raise CollectorError(f"requested adb serial is not online: {serial}")
        resolved = serial
    elif len(online) == 1:
        resolved = online[0]
    elif not online:
        raise CollectorError("no adb device is online")
    else:
        raise CollectorError("multiple adb devices are online; pass --serial")

    version_name = run_command(
        adb_args(resolved, "shell", "dumpsys", "package", package), check=False
    )
    version = None
    m = re.search(r"versionName=([^\s]+)", version_name)
    if m:
        version = m.group(1)
    return {
        "adb_serial": resolved,
        "manufacturer": get_prop(resolved, "ro.product.manufacturer"),
        "model": get_prop(resolved, "ro.product.model"),
        "device": get_prop(resolved, "ro.product.device"),
        "fingerprint": get_prop(resolved, "ro.build.fingerprint"),
        "sdk": get_prop(resolved, "ro.build.version.sdk"),
        "android_release": get_prop(resolved, "ro.build.version.release"),
        "package": package,
        "app_version_name": version,
    }


def summarize(samples: Iterable[ResourceSample]) -> dict[str, object]:
    rows = list(samples)
    def nums(name: str) -> list[float]:
        return [float(getattr(r, name)) for r in rows if getattr(r, name) is not None]
    def stat(name: str) -> dict[str, float | None]:
        values = nums(name)
        if not values:
            return {"min": None, "mean": None, "max": None}
        return {
            "min": min(values),
            "mean": sum(values) / len(values),
            "max": max(values),
        }
    return {
        "sample_count": len(rows),
        "cpu_pct": stat("cpu_pct"),
        "pss_kb": stat("pss_kb"),
        "java_heap_kb": stat("java_heap_kb"),
        "native_heap_kb": stat("native_heap_kb"),
        "battery_level_pct": stat("battery_level_pct"),
        "battery_temperature_c": stat("battery_temperature_c"),
        "observed_pids": sorted({r.pid for r in rows if r.pid is not None}),
        "thermal_statuses": sorted({r.thermal_status for r in rows if r.thermal_status}),
    }


def pull_wake_ledger(serial: str, package: str, destination: Path) -> bool:
    out = run_command(
        adb_args(
            serial,
            "exec-out",
            "run-as",
            package,
            "cat",
            "files/wake_diagnostics/wake_diagnostic_events.jsonl",
        ),
        check=False,
    )
    if not out.strip():
        return False
    destination.write_text(out, encoding="utf-8")
    return True


def collect(args: argparse.Namespace) -> int:
    metadata = device_metadata(args.serial, args.package)
    serial = str(metadata["adb_serial"])
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    session = {
        "schema": "okja.fold4-evidence-session.v1",
        "started_at_utc": started.isoformat(),
        "requested_duration_s": args.duration_seconds,
        "sample_interval_s": args.interval_seconds,
        "privacy": "aggregate_resource_metadata_only_no_transcripts_no_raw_audio",
        "device": metadata,
    }
    (out_dir / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    samples: list[ResourceSample] = []
    deadline = time.monotonic() + args.duration_seconds
    samples_path = out_dir / "resource_samples.jsonl"
    with samples_path.open("w", encoding="utf-8") as fh:
        while True:
            sample = capture_sample(serial, args.package)
            samples.append(sample)
            fh.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")
            fh.flush()
            if time.monotonic() >= deadline:
                break
            time.sleep(args.interval_seconds)

    pulled = False
    if not args.no_pull_wake_ledger:
        pulled = pull_wake_ledger(serial, args.package, out_dir / "wake_diagnostic_events.jsonl")

    summary = summarize(samples)
    summary.update({
        "schema": "okja.fold4-evidence-summary.v1",
        "started_at_utc": started.isoformat(),
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "wake_ledger_pulled": pulled,
        "human_cycle_record_required": True,
        "human_cycle_record_note": "Record >=20 full wake-command-response attempts separately; this collector intentionally does not persist transcript content.",
    })
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serial")
    p.add_argument("--package", default=PACKAGE)
    p.add_argument("--duration-seconds", type=int, default=600)
    p.add_argument("--interval-seconds", type=int, default=10)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--no-pull-wake-ledger", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.duration_seconds < 1 or args.interval_seconds < 1:
        raise SystemExit("duration and interval must be positive")
    try:
        return collect(args)
    except CollectorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
