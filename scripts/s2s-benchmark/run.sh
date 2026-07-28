#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=models.env
. "$SCRIPT_DIR/models.env"
ROOT=${S2S_BENCH_ROOT:-/var/tmp/saha-s2s-benchmark}
RESULTS="$ROOT/results/$(date -u +%Y%m%dT%H%M%SZ)"
AUDIO_DIR=${S2S_AUDIO_DIR:-$ROOT/audio}
mkdir -p "$RESULTS"

exec > >(tee "$RESULTS/benchmark.log") 2>&1
printf 'started=%s\n' "$(date -Is)"
uname -a
cat /etc/os-release
free -b
df -B1 "$ROOT"
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
(timeout 3 tegrastats --interval 500 || true) >"$RESULTS/tegrastats-baseline.txt"

LLAMA_CLI=$(find "$ROOT/tools" -type f -name llama-cli -perm -111 -print -quit)
SHERPA_CLI=$(find "$ROOT/tools" -type f -name sherpa-onnx-offline -perm -111 -print -quit)
PARAFORMER_DIR=$(find "$ROOT/models" -maxdepth 1 -type d -name 'sherpa-onnx-paraformer-zh-small-*' -print -quit)
[ -n "$LLAMA_CLI" ] && [ -n "$SHERPA_CLI" ] && [ -n "$PARAFORMER_DIR" ] || {
  echo 'Run prepare.sh first.' >&2; exit 1;
}

for seconds in 5 15 30; do
  wav="$AUDIO_DIR/mandarin-${seconds}s.wav"
  [ -f "$wav" ] || { echo "Missing controlled 16-kHz mono fixture: $wav" >&2; exit 1; }
  /usr/bin/time -v "$SHERPA_CLI" \
    --tokens="$PARAFORMER_DIR/tokens.txt" \
    --paraformer="$PARAFORMER_DIR/model.int8.onnx" \
    --num-threads="${SHERPA_THREADS:-4}" "$wav" \
    2>&1 | tee "$RESULTS/paraformer-${seconds}s.txt"
done

for spec in \
  "small:$ROOT/models/$LLM_SMALL_FILE" \
  "large:$ROOT/models/$LLM_LARGE_FILE"; do
  name=${spec%%:*}; model=${spec#*:}
  /usr/bin/time -v "$LLAMA_CLI" -m "$model" -ngl 99 -c 4096 -n 128 \
    --temp 0 -p '请用三句话说明机器人如何安全地在人群中移动。' \
    2>&1 | tee "$RESULTS/llm-$name.txt"
done

cat >"$RESULTS/tts-whisper-probes.txt" <<EOF
Qwen3-TTS CUDA benchmark not run automatically. Gate it on all of:
- isolated Python 3.12 runtime
- ARM64 PyTorch reporting CUDA available
- qwen-tts import success without x86-only flash-attn/triton wheels
- first 20-character synthesis succeeds before downloading the second checkpoint
Pinned: $TTS_SMALL_ID@$TTS_SMALL_REVISION and $TTS_LARGE_ID@$TTS_LARGE_REVISION
Fallback: $TTS_FALLBACK_ID@$TTS_FALLBACK_REVISION (sherpa-onnx CPU)
Faster Whisper blocker gate: ARM64 CUDA CTranslate2 wheel/build compatible with CUDA 13.2.
Pinned: $WHISPER_ID@$WHISPER_REVISION
EOF

free -b >"$RESULTS/memory-after.txt"
(timeout 3 tegrastats --interval 500 || true) >"$RESULTS/tegrastats-after.txt"
docker inspect -f '{{.Name}} {{.State.Status}} {{.State.StartedAt}}' livekit-server livekit-agent >"$RESULTS/livekit-after.txt"
echo "Results: $RESULTS"
