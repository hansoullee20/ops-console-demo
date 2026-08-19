# Okja Voice Engine Benchmark Plan

All engines must receive the same recorded PCM corpus. Microphone behavior is benchmarked separately on-device.

## ASR candidates

- Android SpeechRecognizer via external audio source: compatibility/fallback only
- sherpa-onnx Korean streaming Zipformer
- sherpa-onnx Moonshine tiny-ko

Measure per engine:

- full-utterance preservation for connected `옥자야 + command`
- WER / exact-command accuracy
- first partial latency
- final latency
- wake-event to first token latency
- CPU
- peak PSS/RSS
- 30 min and 8 h thermal/battery behavior

## Wake candidates

- Porcupine low-level PCM API: baseline
- sherpa-onnx KWS: architecture-fit candidate

Wake engines consume the canonical `PcmAudioSource`; high-level APIs that acquire a microphone are excluded.

Measure:

- false reject rate
- false activations/hour
- keyword-end to detection latency
- CPU / PSS
- TV/background-speech robustness
- elderly/quiet-speaker robustness

## Initial device gates

Target: Galaxy Z Fold4 / SM-F936N.

- connected wake+command continuity >= 98/100
- duplicate command execution = 0
- final local path system recognition cue = 0
- one active AudioRecord throughout wake -> ASR
- false activation target <= 0.2/hour in the first long-negative gate

Mode F remains a short compatibility test and cannot become the production architecture merely by passing these gates.
