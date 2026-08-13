# Okja device-command boundary

`okja.device-command.v1` is the guarded boundary between a resolved product
intent and a device-specific adapter. An LLM response is not a command and must
not call an adapter directly.

## Supported contract surface

- TV: power on/off, resume last source, volume up/down, set channel.
- Air conditioner: power on/off, set temperature from 16–30 °C, set mode to
  auto/cool/dry/fan.
- Phone finder: ring for 5–120 seconds, or cancel.
- Washer: action names are reserved, but the capability is explicitly disabled
  until a physical integration exists.

The capability manifest describes the contract surface. An enabled capability
still requires a runtime adapter; without one, the boundary emits a cached
`command.failed` event with `adapter_unavailable` and performs no action.

## Idempotency and failure semantics

The service durably reserves `idempotency_key` in SQLite before invoking an
adapter.

- An exact completed duplicate returns the original event IDs and result with
  `replayed=true`; the adapter is not called again.
- Reusing a key for different command content is rejected.
- A concurrent duplicate returns `in_progress`; it does not call the adapter.
- Success, adapter failure, unavailable adapters and disabled capabilities are
  cached durably.
- If the process stops after reservation, the key remains `in_progress` and is
  not automatically retried. Reconciliation is required because duplicating a
  physical action is less safe than surfacing an unresolved state.

Requests expire, may be valid for at most five minutes, and cannot be issued
more than 30 seconds in the future. Target/action parameter objects are exact;
unknown fields and unsupported combinations fail before idempotency reservation.

## Event chain

An executable request emits `command.accepted`, then either
`command.completed` or `command.failed`. The terminal event is caused by the
accepted event. Disabled or unavailable capabilities emit only
`command.failed`, caused by the upstream `source_event_id`. All command events
use `okja.event.v1`, keep the original device/profile/session/correlation IDs,
and use audit retention.

This contract does not prove a TV, AC or phone-finder adapter works on physical
hardware. Those flows and device tests remain separate release gates.
