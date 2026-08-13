# Okja care and family event contract

Care/family events are strict `okja.event.v1` envelopes created and validated
by `okja_care_events.py`. Agent/LLM sources are not allowed producers.

## Event families

- Wellness prompts and responses. Every prompt must allow both snooze and
  decline; records require health-journal consent.
- Symptom records. Payloads store the user's report, optional body area and
  self-reported severity. The exact contract has no diagnosis or medical
  assessment field. Sharing additionally requires caregiver-sharing consent.
- Presence arrival/departure. Every event says whether it is estimated,
  confirmed or corrected and records confidence plus evidence-source types.
- Family ETA. The sender identity must match the envelope profile and
  caregiver-sharing consent is required.
- Notification requested/delivered/failed. Requests must match the profile's
  enabled event category, configured caregiver ID and channel. They carry a
  bounded summary code rather than arbitrary sensitive prose, and thei
  source-event reference must match the envelope causation ID.

The validator fixes privacy, retention and severity by event type. Health
records use health privacy/user-record retention; presence and ETA use bounded
history; notification lifecycle events use audit retention. Emergency
notification requests are critical/emergency-classified but do not represent
or authorize a 119 call.

This contract does not implement sensors, notification providers or product UI.
Those integrations retain their own release gates.
