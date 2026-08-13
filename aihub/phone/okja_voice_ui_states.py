#!/usr/bin/env python3
"""Platform-independent contract for Okja's visible voice trust/recovery states."""
from __future__ import annotations

STATES = frozenset({
    "READY", "LISTENING", "THINKING", "MIC_OFF", "OFFLINE_DEGRADED", "ERROR_RECOVERY"
})


def microphone_allowed(state: str) -> bool:
    _require(state)
    return state != "MIC_OFF"


def manual_talk_enabled(state: str) -> bool:
    _require(state)
    return state not in {"MIC_OFF", "THINKING"}


def automatic_wake_allowed(state: str) -> bool:
    _require(state)
    return state in {"READY", "OFFLINE_DEGRADED", "ERROR_RECOVERY"}


def _require(state: str) -> None:
    if state not in STATES:
        raise ValueError(f"unknown voice UI state: {state}")
