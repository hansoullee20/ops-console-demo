package com.soul.aihub;

import android.os.SystemClock;

import org.json.JSONException;
import org.json.JSONObject;

import java.time.Instant;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

/** Strict Android producer/consumer for the Okja event envelope v1. */
public final class OkjaEventEnvelope {
    public static final String SCHEMA_VERSION = "okja.event.v1";

    private static final Pattern ID_PATTERN = Pattern.compile(
            "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$");
    private static final Pattern SOURCE_PATTERN = Pattern.compile(
            "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$");
    private static final Set<String> EVENT_TYPES = set(
            "wake.candidate", "wake.detected", "wake.rejected",
            "listening.started", "listening.stopped", "listening.failed",
            "transcript.partial", "transcript.final", "transcript.failed",
            "intent.requested", "intent.resolved", "intent.failed",
            "confirmation.requested", "confirmation.accepted", "confirmation.rejected",
            "command.accepted", "command.completed", "command.failed",
            "assistant.response", "assistant.failed",
            "tts.started", "tts.completed", "tts.failed",
            "emergency.confirmation_requested", "emergency.dismissed",
            "emergency.ready", "emergency.escalation_started", "emergency.resolved");
    private static final Set<String> SEVERITIES = set(
            "debug", "info", "notice", "warning", "error", "critical");
    private static final Set<String> PRIVACY_CLASSES = set(
            "public", "household", "personal", "sensitive", "health", "emergency");
    private static final Set<String> RETENTION_CLASSES = set(
            "volatile", "diagnostic_7d", "history_30d", "user_record",
            "benchmark_fixed", "audit");
    private static final Set<String> REQUIRED_FIELDS = set(
            "schema_version", "event_id", "event_type", "occurred_at",
            "monotonic_ms", "device_id", "profile_id", "session_id",
            "correlation_id", "causation_id", "source", "severity",
            "privacy_class", "retention_class", "payload");

    private OkjaEventEnvelope() {}

    public static JSONObject create(String eventType, String deviceId, String profileId,
                                    String sessionId, String correlationId,
                                    String causationId, String source, String severity,
                                    String privacyClass, String retentionClass,
                                    JSONObject payload) throws JSONException {
        JSONObject event = new JSONObject();
        event.put("schema_version", SCHEMA_VERSION);
        event.put("event_id", UUID.randomUUID().toString());
        event.put("event_type", eventType);
        event.put("occurred_at", Instant.now().toString());
        event.put("monotonic_ms", SystemClock.elapsedRealtime());
        event.put("device_id", deviceId);
        event.put("profile_id", profileId);
        event.put("session_id", sessionId);
        event.put("correlation_id", correlationId);
        event.put("causation_id", causationId == null ? JSONObject.NULL : causationId);
        event.put("source", source);
        event.put("severity", severity);
        event.put("privacy_class", privacyClass);
        event.put("retention_class", retentionClass);
        event.put("payload", payload == null ? new JSONObject() : payload);
        validate(event);
        return event;
    }

    public static JSONObject validate(JSONObject event) throws JSONException {
        if (event == null) throw new JSONException("event required");
        Set<String> keys = new HashSet<>();
        Iterator<String> iterator = event.keys();
        while (iterator.hasNext()) keys.add(iterator.next());
        if (!keys.equals(REQUIRED_FIELDS)) {
            throw new JSONException("event fields must exactly match v1 envelope");
        }
        requireEquals(event, "schema_version", SCHEMA_VERSION);
        String eventId = requiredString(event, "event_id");
        try {
            UUID.fromString(eventId);
        } catch (IllegalArgumentException error) {
            throw new JSONException("event_id must be UUID");
        }
        requireRegistered(event, "event_type", EVENT_TYPES);
        String occurredAt = requiredString(event, "occurred_at");
        if (!occurredAt.endsWith("Z")) {
            throw new JSONException("occurred_at must end in Z");
        }
        try {
            Instant.parse(occurredAt);
        } catch (Exception error) {
            throw new JSONException("occurred_at must be UTC RFC3339");
        }
        double monotonicMs = event.getDouble("monotonic_ms");
        if (!Double.isFinite(monotonicMs) || monotonicMs < 0) {
            throw new JSONException("monotonic_ms must be finite and non-negative");
        }
        requireId(event, "device_id");
        requireId(event, "profile_id");
        requireId(event, "session_id");
        requireId(event, "correlation_id");
        if (!event.isNull("causation_id")) requireId(event, "causation_id");
        if (!SOURCE_PATTERN.matcher(requiredString(event, "source")).matches()) {
            throw new JSONException("source has invalid syntax");
        }
        requireRegistered(event, "severity", SEVERITIES);
        requireRegistered(event, "privacy_class", PRIVACY_CLASSES);
        requireRegistered(event, "retention_class", RETENTION_CLASSES);
        event.getJSONObject("payload");
        return event;
    }

    public static JSONObject requireResponseFor(JSONObject response, JSONObject request)
            throws JSONException {
        validate(response);
        validate(request);
        String type = response.getString("event_type");
        if (!type.equals("assistant.response") && !type.equals("assistant.failed")) {
            throw new JSONException("unexpected bridge response event_type");
        }
        requireEquals(response, "source", "bridge.agent");
        requireEquals(response, "privacy_class", "personal");
        requireEquals(response, "retention_class", "volatile");
        for (String field : Arrays.asList(
                "device_id", "profile_id", "session_id", "correlation_id")) {
            if (!response.getString(field).equals(request.getString(field))) {
                throw new JSONException("bridge response " + field + " mismatch");
            }
        }
        if (response.isNull("causation_id")
                || !response.getString("causation_id").equals(request.getString("event_id"))) {
            throw new JSONException("bridge response causation_id mismatch");
        }
        JSONObject payload = response.getJSONObject("payload");
        Set<String> payloadKeys = new HashSet<>();
        Iterator<String> payloadIterator = payload.keys();
        while (payloadIterator.hasNext()) payloadKeys.add(payloadIterator.next());
        if (type.equals("assistant.response")) {
            requireEquals(response, "severity", "info");
            if (!payloadKeys.equals(set("text"))) {
                throw new JSONException("assistant.response payload must contain only text");
            }
            payload.getString("text");
        } else {
            requireEquals(response, "severity", "error");
            if (!payloadKeys.equals(set("error_code", "message"))) {
                throw new JSONException("assistant.failed payload must contain exact error fields");
            }
            payload.getString("error_code");
            payload.getString("message");
        }
        return response;
    }

    private static void requireEquals(JSONObject event, String field, String value)
            throws JSONException {
        if (!requiredString(event, field).equals(value)) {
            throw new JSONException(field + " mismatch");
        }
    }

    private static void requireRegistered(JSONObject event, String field, Set<String> allowed)
            throws JSONException {
        if (!allowed.contains(requiredString(event, field))) {
            throw new JSONException(field + " is not registered for v1");
        }
    }

    private static String requiredString(JSONObject event, String field) throws JSONException {
        String value = event.getString(field);
        if (value == null || value.isEmpty()) throw new JSONException(field + " required");
        return value;
    }

    private static void requireId(JSONObject event, String field) throws JSONException {
        if (!ID_PATTERN.matcher(requiredString(event, field)).matches()) {
            throw new JSONException(field + " has invalid syntax");
        }
    }

    private static Set<String> set(String... values) {
        return new HashSet<>(Arrays.asList(values));
    }
}
