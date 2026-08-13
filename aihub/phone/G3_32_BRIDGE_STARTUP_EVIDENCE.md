# G3.32 — Lazy/resilient bridge startup evidence

Status: COMPLETE.

## Defect addressed

The bridge previously entered both `ClaudeSDKClient` async contexts before binding TCP `127.0.0.1:8765`. A slow or failed SDK initialization could therefore prevent the local bridge socket from becoming available at all.

## Implementation

- `okja_lazy_agent_pool.py` holds profile client factories without invoking them during construction.
- `aihub_bridge.py` constructs the lazy pool, defines the request handler, and binds the localhost server without creating either Claude client.
- The requested profile client is initialized only inside the request handler on the first assistant query.
- Per-profile initialization locks prevent duplicate concurrent startup.
- A failed initialization is not cached, so a later request retries it.
- Grandma and personal clients initialize independently; a failure in one does not prevent the other profile from being initialized.
- Existing intent/confirmation responses that do not require the agent remain serviceable without initializing an SDK client.

## Verification

- `test_okja_lazy_agent_pool.py` verifies lazy construction, one-time concurrent initialization, retry after failed initialization, independent profile initialization, and fail-closed unknown profiles.
- `test_bridge_lazy_startup_contract.py` guards the live bridge source against reintroducing direct eager `ClaudeSDKClient` context entry and verifies `pool.get()` exists only inside the request handler while the server bind remains in `main`.
- Run `31693869837` passed the initial lazy-pool suite.
- Final run `31693994203` passed the full phone/evaluator suite including the server-first bridge source contract.

## Closure boundary

G3.32 concerns bridge startup/recovery architecture. It does not prove long-duration Fold4 operation; G3.29, G3.30 and G3.33 remain the physical-device reliability gates.
