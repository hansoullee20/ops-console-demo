# Okja guarded emergency state machine

The emergency boundary is deterministic and confirm-before-escalate. Agent or
LLM output is advisory text only; it is not accepted as a signal, a human
response, a policy timeout, or an escalation authorization.

## States

1. A trusted sensor, user, caregiver or physical device button opens a case in
   `awaiting_confirmation` and emits `emergency.confirmation_requested`.
2. A user/caregiver `safe` response resolves the case. A user/caregiver
   `needs_help` response or trusted policy-timer `timeout` moves it only to
   `ready_to_escalate`.
3. Escalation starts only after an HMAC authorization bound to the exact case
   ID, state version, channel and short expiry.
4. The only enabled channel is `family_notification`. Automatic emergency
   services/119 is absent from the allowed registry.

All state and processed input IDs are persisted in SQLite. Exact replays return
the original event, while reuse of an input ID with different content fails.
Events use `okja.event.v1`, emergency privacy classification and audit retention.

## Agent isolation

The bridge emits only `assistant.response` or `assistant.failed`. It does not
parse agent prose into device commands or emergency transitions. The emergency
module exposes `agent_advisory()` only to report the current state; the supplied
text is not persisted and never changes state.

Trusted signal adapters and the policy signer must live outside the agent
prompt/tool surface. The policy secret must be at least 32 bytes and provided
from trusted runtime configuration, never from model output.

## Scope

This state machine proves the G3 guard boundary. It does not prove fall
detection, microphone/UI confirmation, caregiver delivery, target-device
behavior, telephony, 119 integration, or a complete detect/ask/wait field test.
Those remain later physical, human and legal gates.
