package com.soul.aihub;

/** Explicit trust/recovery states for the live voice UI. */
public final class VoiceUiState {
    public enum State {
        READY,
        LISTENING,
        THINKING,
        MIC_OFF,
        OFFLINE_DEGRADED,
        ERROR_RECOVERY
    }

    private VoiceUiState() {}

    public static boolean microphoneAllowed(State state) {
        return state != State.MIC_OFF;
    }

    public static boolean manualTalkEnabled(State state) {
        return state != State.MIC_OFF && state != State.THINKING;
    }

    public static boolean automaticWakeAllowed(State state) {
        return state == State.READY
                || state == State.OFFLINE_DEGRADED
                || state == State.ERROR_RECOVERY;
    }
}
