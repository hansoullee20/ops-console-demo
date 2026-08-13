package com.soul.aihub;

import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/** Volatile bounded event ledger. It never writes transcripts or events to disk. */
public final class VoiceEventLedger {
    private final int capacity;
    private final ArrayDeque<JSONObject> events = new ArrayDeque<>();

    public VoiceEventLedger(int capacity) {
        if (capacity < 1) throw new IllegalArgumentException("capacity must be positive");
        this.capacity = capacity;
    }

    public synchronized JSONObject record(JSONObject event) {
        if (event == null) throw new IllegalArgumentException("event required");
        while (events.size() >= capacity) events.removeFirst();
        events.addLast(event);
        return event;
    }

    public synchronized List<JSONObject> snapshot() {
        return new ArrayList<>(events);
    }

    public synchronized int size() {
        return events.size();
    }

    public synchronized void clear() {
        events.clear();
    }
}
