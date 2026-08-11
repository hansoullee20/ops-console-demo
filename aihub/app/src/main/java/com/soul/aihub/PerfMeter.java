package com.soul.aihub;

import android.os.Debug;
import android.os.Process;
import android.os.SystemClock;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Locale;

final class PerfMeter {
    private static final long WINDOW_MS = 60_000L;

    private static final class Sample {
        final long wallMs;
        final long cpuDeltaMs;
        final long wallDeltaMs;

        Sample(long wallMs, long cpuDeltaMs, long wallDeltaMs) {
            this.wallMs = wallMs;
            this.cpuDeltaMs = cpuDeltaMs;
            this.wallDeltaMs = wallDeltaMs;
        }
    }

    private final long startedWallMs;
    private final long startedCpuMs;
    private long lastWallMs;
    private long lastCpuMs;
    private double peakCpuPct = 0.0;
    private double peakPssMb = 0.0;
    private double peakJavaMb = 0.0;
    private final Deque<Sample> recent = new ArrayDeque<>();

    PerfMeter() {
        startedWallMs = SystemClock.elapsedRealtime();
        startedCpuMs = Process.getElapsedCpuTime();
        lastWallMs = startedWallMs;
        lastCpuMs = startedCpuMs;
    }

    String snapshot(String modeLabel) {
        long nowWall = SystemClock.elapsedRealtime();
        long nowCpu = Process.getElapsedCpuTime();
        long wallDelta = Math.max(1L, nowWall - lastWallMs);
        long cpuDelta = Math.max(0L, nowCpu - lastCpuMs);
        double nowPct = cpuDelta * 100.0 / wallDelta;
        peakCpuPct = Math.max(peakCpuPct, nowPct);

        recent.addLast(new Sample(nowWall, cpuDelta, wallDelta));
        while (!recent.isEmpty() && nowWall - recent.peekFirst().wallMs > WINDOW_MS) {
            recent.removeFirst();
        }

        long recentCpu = 0L;
        long recentWall = 0L;
        for (Sample s : recent) {
            recentCpu += s.cpuDeltaMs;
            recentWall += s.wallDeltaMs;
        }
        double avg1m = recentCpu * 100.0 / Math.max(1L, recentWall);

        long totalWall = Math.max(1L, nowWall - startedWallMs);
        long totalCpu = Math.max(0L, nowCpu - startedCpuMs);
        double avgTotal = totalCpu * 100.0 / totalWall;

        double pssMb = Debug.getPss() / 1024.0;
        Runtime rt = Runtime.getRuntime();
        double javaMb = (rt.totalMemory() - rt.freeMemory()) / (1024.0 * 1024.0);
        peakPssMb = Math.max(peakPssMb, pssMb);
        peakJavaMb = Math.max(peakJavaMb, javaMb);

        long upSec = totalWall / 1000L;
        lastWallMs = nowWall;
        lastCpuMs = nowCpu;

        return String.format(Locale.US,
                "%s · %02d:%02d\nCPU now %.1f%% · avg1m %.1f%% · avg total %.1f%% · peak %.1f%%\nPSS %.1f MB · peak %.1f MB · Java %.1f MB · peak %.1f MB",
                modeLabel,
                upSec / 60,
                upSec % 60,
                nowPct,
                avg1m,
                avgTotal,
                peakCpuPct,
                pssMb,
                peakPssMb,
                javaMb,
                peakJavaMb);
    }
}
