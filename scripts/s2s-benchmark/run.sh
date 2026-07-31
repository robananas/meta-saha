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

if docker image inspect "${SAHA_S2S_IMAGE:-roban-s2s:arm64}" >/dev/null 2>&1 && [ -d /data/models/s2s ]; then
  timeout 90 tegrastats --interval 500 >"$RESULTS/tegrastats-sherpa-cuda.txt" 2>&1 &
  monitor_pid=$!
  docker run --rm --runtime nvidia --entrypoint python \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    -e CUDA_VISIBLE_DEVICES=0 \
    -e ROBAN_S2S_MODEL_ROOT=/models \
    -e ROBAN_S2S_KWS_PROVIDER=cuda \
    -e ROBAN_S2S_VAD_PROVIDER=cuda \
    -e ROBAN_S2S_STT_PROVIDER=cuda \
    -e ROBAN_S2S_TTS_PROVIDER=cuda \
    -e ROBAN_S2S_STT_BACKEND=sherpa-onnx \
    -e ROBAN_S2S_TTS_BACKEND=sherpa-onnx-vits \
    -e ROBAN_S2S_LLM_MODEL=benchmark-smoke \
    -e ROBAN_S2S_PIPELINE_FACTORY=roban_voice_s2s.production_pipeline:create_pipeline \
    -v /data/models/s2s:/models:ro \
    "${SAHA_S2S_IMAGE:-roban-s2s:arm64}" -m roban_voice_s2s.cuda_smoke \
    2>&1 | tee "$RESULTS/sherpa-cuda-four-stage.json"
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
fi

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
