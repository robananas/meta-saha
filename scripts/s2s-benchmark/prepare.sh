#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=models.env
. "$SCRIPT_DIR/models.env"

ROOT=${S2S_BENCH_ROOT:-/var/tmp/saha-s2s-benchmark}
HF_ENDPOINT=${HF_ENDPOINT:-$HF_ENDPOINT_DEFAULT}
PIP_INDEX_URL=${PIP_INDEX_URL:-$PIP_INDEX_URL_DEFAULT}
GITHUB_PROXY=${GITHUB_PROXY:-$GITHUB_PROXY_DEFAULT}
DRY_RUN=0
[ "${1:-}" != "--dry-run" ] || DRY_RUN=1

mkdir_cmd() { printf 'mkdir -p %q\n' "$1"; [ "$DRY_RUN" = 1 ] || mkdir -p "$1"; }
fetch() {
  local official=$1 output=$2 sha=${3:-}
  local url=$official
  if [ -n "$GITHUB_PROXY" ] && [[ "$official" == https://github.com/* ]]; then
    url="${GITHUB_PROXY%/}/$official"
  fi
  printf 'curl -fL --retry 3 --continue-at - %q -o %q\n' "$url" "$output"
  if [ "$DRY_RUN" = 0 ]; then
    if ! curl -fL --retry 3 --continue-at - "$url" -o "$output"; then
      echo "Mirror failed; retrying official source: $official" >&2
      curl -fL --retry 3 --continue-at - "$official" -o "$output"
    fi
    if [ -n "$sha" ]; then printf '%s  %s\n' "$sha" "$output" | sha256sum -c -; fi
  fi
}
hf_fetch() {
  local repo=$1 revision=$2 file=$3 output=$4
  local mirror="${HF_ENDPOINT%/}/$repo/resolve/$revision/$file"
  local official="${HF_ENDPOINT_OFFICIAL%/}/$repo/resolve/$revision/$file"
  printf 'curl -fL --retry 3 --continue-at - %q -o %q\n' "$mirror" "$output"
  if [ "$DRY_RUN" = 0 ]; then
    if ! curl -fL --retry 3 --continue-at - "$mirror" -o "$output"; then
      echo "HF mirror failed; retrying official source: $official" >&2
      curl -fL --retry 3 --continue-at - "$official" -o "$output"
    fi
  fi
}

for d in "$ROOT" "$ROOT/downloads" "$ROOT/tools" "$ROOT/models" "$ROOT/results" "$ROOT/venvs"; do mkdir_cmd "$d"; done
fetch "https://github.com/hybridgroup/llama-cpp-builder/releases/download/$LLAMA_CPP_TAG/$LLAMA_CPP_ASSET" "$ROOT/downloads/$LLAMA_CPP_ASSET" "$LLAMA_CPP_SHA256"
fetch "https://github.com/k2-fsa/sherpa-onnx/releases/download/$SHERPA_ONNX_TAG/$SHERPA_ONNX_ASSET" "$ROOT/downloads/$SHERPA_ONNX_ASSET"
fetch "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$PARAFORMER_ASSET" "$ROOT/downloads/$PARAFORMER_ASSET"
hf_fetch "$LLM_SMALL_ID" "$LLM_SMALL_REVISION" "$LLM_SMALL_FILE" "$ROOT/models/$LLM_SMALL_FILE"
hf_fetch "$LLM_LARGE_ID" "$LLM_LARGE_REVISION" "$LLM_LARGE_FILE" "$ROOT/models/$LLM_LARGE_FILE"

cat <<EOF
Pinned TTS repositories are intentionally not downloaded by default because their
ARM64 CUDA runtime must pass the probe first:
  HF_ENDPOINT=$HF_ENDPOINT PIP_INDEX_URL=$PIP_INDEX_URL
  $TTS_SMALL_ID@$TTS_SMALL_REVISION
  $TTS_LARGE_ID@$TTS_LARGE_REVISION
Faster Whisper is likewise probe-only until an ARM64 CUDA CTranslate2 build exists:
  $WHISPER_ID@$WHISPER_REVISION
EOF

if [ "$DRY_RUN" = 0 ]; then
  tar -xzf "$ROOT/downloads/$LLAMA_CPP_ASSET" -C "$ROOT/tools"
  tar -xjf "$ROOT/downloads/$SHERPA_ONNX_ASSET" -C "$ROOT/tools"
  tar -xjf "$ROOT/downloads/$PARAFORMER_ASSET" -C "$ROOT/models"
  sha256sum "$ROOT"/downloads/* "$ROOT"/models/*.gguf >"$ROOT/results/artifact-sha256.txt"
  du -sb "$ROOT"/downloads/* "$ROOT"/models/* >"$ROOT/results/artifact-sizes-bytes.txt"
fi
