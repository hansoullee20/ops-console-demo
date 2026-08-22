# Project Okja — Security Backlog

Last updated: 2026-08-19

This document records known security risks that are **not allowed to disappear just because the current family prototype prioritizes functionality**.

Current product decision: security hardening should not block basic prototype work with a small trusted family group and limited device control. However, several items become mandatory release gates before broader deployment or security-sensitive actuators.

## Current security posture

**Prototype status: acceptable for controlled family testing only.**

**Production / broader household deployment: NO-GO until the release-gate items below are closed.**

The current prototype assumes:

- trusted physical access to the test phone;
- a small number of known family users;
- no hostile Android app/process on the same phone;
- no sensitive actuator such as door lock, alarm disarm, camera privacy control, purchase/payment, or account-management action;
- current device testing is limited to low-impact household control such as AC/TV-class actions.

If any of those assumptions stops being true, the related deferred item becomes active work immediately.

---

## SEC-001 — Authenticate the local bridge peer

**Severity before broader deployment: Critical**

### Current behavior

The Android app talks to a localhost TCP bridge on `127.0.0.1:8765` using a length-prefixed JSON event protocol.

Event fields such as `source=android.voice`, `device_id`, `session_id`, and `correlation_id` are validated structurally but are not cryptographic proof of who sent the packet.

### Risk

A malicious local app/process could potentially impersonate the Okja Android client or a fake bridge process could impersonate the server.

### Prototype decision

Deferred while the test environment is controlled.

### Becomes blocking when

- Okja is installed on phones with untrusted third-party apps;
- the bridge moves beyond a tightly controlled local prototype;
- real sensitive device adapters are connected;
- multiple households/devices are supported.

### Target fix

Prefer an authenticated local IPC boundary. If a separate companion process remains necessary, use cryptographic pairing/authentication, per-message integrity, nonce/replay protection, and explicit peer identity.

---

## SEC-002 — Enforce authorization at the actuator boundary

**Severity once real adapters exist: Critical**

### Current behavior

`DeviceCommandService` strongly validates command shape, target/action, parameter bounds, expiry, idempotency, and at-most-once behavior.

However, a syntactically valid command does not yet carry cryptographic or durable proof that the user-confirmation/policy layer actually authorized that exact physical action.

### Risk

If an upstream component is compromised or bypassed, it may be able to manufacture a valid-looking command that reaches a physical adapter.

### Prototype decision

Deferred while no security-sensitive physical adapter is enabled.

### Becomes blocking when

Any adapter performs real physical action beyond controlled low-impact tests.

### Target fix

Make the actuator accept an `AuthorizedCommand` (or equivalent capability) that binds at least:

- target;
- action;
- exact parameters hash;
- session/correlation;
- authorization event/grant;
- expiry;
- nonce / replay protection;
- policy version.

The adapter boundary should reject ordinary free-form or merely structurally valid commands.

---

## SEC-003 — Do not use a coding agent as the long-term household AI sandbox

**Severity for production: High**

### Current behavior

The Codex prototype bridge invokes `codex exec` for ordinary assistant queries. This avoids shell interpolation because `create_subprocess_exec()` is used, but the spawned tool is still a general coding agent rather than a narrow chat-only runtime.

### Risk

A household utterance or prompt-injection path should not gain broad filesystem/shell/tool capabilities merely because it reached the conversational fallback.

### Prototype decision

Allowed as a development backend while the machine/environment contains no sensitive household secrets and no direct actuator authority is exposed to the model.

### Becomes blocking when

- the backend stores household credentials/state;
- the model can directly invoke device adapters;
- the prototype becomes a persistent household service;
- other users rely on the system beyond development testing.

### Target fix

Use a least-privilege conversational provider boundary with no general shell/filesystem/device authority. Keep deterministic device execution outside the model.

---

## SEC-004 — Voice confirmation is safety, not identity

**Severity depends on actuator: High for sensitive actions**

### Current behavior

The intent layer requires explicit confirmation for current device commands and scopes confirmation to device/profile/session/correlation.

### Risk

A TV, recording, visitor, malicious speaker, or compromised audio source may potentially reproduce both a command and a confirmation phrase. Speaker recognition is not currently an authentication factor.

### Prototype decision

Acceptable for low-impact AC/TV-class testing.

### Becomes blocking when

Adding actions such as:

- door locks;
- alarm disarming;
- cameras/privacy controls;
- purchases/payments;
- account/security settings;
- destructive appliance actions;
- high-impact emergency cancellation.

### Target fix

Define command risk tiers. High-impact actions require an independent trusted factor such as unlocked-device confirmation, biometric approval, trusted companion approval, or equivalent policy.

---

## SEC-005 — Add bridge DoS / admission controls

**Severity: High in hostile local environment**

### Current behavior

The bridge has packet-size/time limits, but authenticated peer admission, rate limiting, and per-client quotas are not yet implemented. New requests can supersede/cancel in-flight model work.

### Risk

A local malicious process could repeatedly send valid-looking packets to starve legitimate requests or churn model subprocesses.

### Prototype decision

Deferred under trusted-device assumption.

### Target fix

After peer authentication:

- reject unauthenticated peers before expensive parsing/model work;
- add request rate/concurrency limits;
- bound model subprocess creation;
- define backpressure rather than unlimited request churn.

---

## SEC-006 — Detect PCM discontinuity before device execution

**Severity: Medium now; potentially High when voice directly controls actuators**

### Current behavior

The new `AudioEngine` emits 20 ms PCM frames through a bounded `MutableSharedFlow` configured to `DROP_OLDEST` under consumer backpressure.

`PcmFrame` currently carries samples and capture timestamp but no explicit sequence/sample index or discontinuity flag.

### Risk

A slow consumer can silently miss audio. Missing speech can change semantics, including negation, while the downstream ASR may not know that the input was incomplete.

### Target fix

Before voice transcript is authorized for a physical command:

- add monotonic frame/sample sequence metadata;
- make discontinuity/overrun explicit;
- fail closed for device execution if the relevant utterance contains a capture gap;
- consider cursor-based ring-buffer consumption for critical consumers instead of silent frame loss.

### Priority

This should be handled during voice-pipeline v2 rather than postponed to final production hardening because it belongs to the PCM contract itself.

---

## SEC-007 — Separate diagnostic and production builds

**Severity: Medium**

### Current behavior

Diagnostic Activities/traces currently coexist with production-path source on the research branch. Diagnostic traces can contain recognizer candidates, device/build information, and audio recording/playback metadata.

### Risk

A diagnostic build could accidentally be distributed as production or household speech/debug metadata could be retained/exported unnecessarily.

### Target fix

Create a strong build boundary, for example:

- separate diagnostic module or debug flavor;
- `.diag` application ID suffix;
- `Okja Diagnostics` label distinct from production;
- diagnostic Activities absent from release manifest;
- release build disables verbose trace/export paths.

### Priority

Do before any release candidate is distributed beyond controlled testing.

---

## SEC-008 — Secure future LAN / Home Assistant / device adapters

**Severity: Future High**

### Current behavior

The current repository mainly defines contracts and prototype boundaries; production LAN adapters are not yet the stable control plane.

### Risk

Adding Home Assistant, vendor APIs, LAN IR bridges, MQTT, or direct device integrations can expose credentials and new network attack surfaces.

### Release requirements

Each real adapter must define:

- authenticated endpoint identity;
- TLS or equivalently protected transport where applicable;
- least-privilege credentials;
- allowlisted target/device IDs;
- no raw model access to credentials;
- bounded commands and timeouts;
- explicit failure and retry behavior;
- secret redaction in logs.

---

## SEC-009 — Native model/runtime supply-chain verification

**Severity: Future Medium/High**

### Trigger

When sherpa-onnx, Porcupine, or other native model/runtime artifacts are integrated.

### Requirements

- pin exact dependency/runtime versions;
- record model hashes and provenance;
- avoid downloading executable/native artifacts from mutable unofficial URLs at runtime;
- review native library permissions/file access;
- preserve reproducible benchmark/build metadata;
- track licenses and update policy.

---

## Security-positive properties already present

Do not lose these during refactors:

- bridge currently binds to loopback rather than LAN wildcard;
- Android manifest uses `allowBackup=false`;
- known device intents are resolved before generative AI;
- explicit negation patterns prevent obvious `do not`/`하지 마` promotion into device commands;
- confirmation is scoped to the active interaction correlation;
- command parameters are strict and bounded;
- command validity windows are bounded;
- durable idempotency favors at-most-once physical action over automatic duplicate retry;
- disabled/unavailable capabilities fail closed.

---

## Release gates by prototype stage

### Stage A — current family prototype

May defer:

- SEC-001 authenticated IPC;
- SEC-003 production AI sandbox;
- SEC-005 rate limiting;
- high-risk multi-factor authorization.

Must still preserve:

- deterministic command routing;
- confirmation for physical actions;
- strict parameter bounds;
- no direct model-to-adapter path;
- diagnostic awareness.

### Stage B — real low-impact household adapters

Must close or materially mitigate:

- SEC-002 actuator authorization;
- SEC-006 PCM discontinuity integrity;
- SEC-007 diagnostic/release separation;
- adapter-specific parts of SEC-008.

### Stage C — broader deployment / sensitive devices

Must close:

- SEC-001 authenticated IPC;
- SEC-003 least-privilege production AI backend;
- SEC-004 command risk tiers / stronger confirmation;
- SEC-005 DoS/admission controls;
- full SEC-008 network credential/transport hardening;
- SEC-009 supply-chain controls.

## Current security blocker

**None for the controlled family AC/TV-class prototype.**

The first security item that should be implemented during the current voice-pipeline work is **SEC-006 PCM discontinuity detection**, because it affects the correctness and trustworthiness of the new audio contract itself rather than only deployment hardening.
