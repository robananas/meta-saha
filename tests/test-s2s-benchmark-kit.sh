#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
KIT="$ROOT_DIR/scripts/s2s-benchmark"
fail() { echo "FAIL: $*" >&2; exit 1; }
for file in README.md models.env prepare.sh run.sh; do [ -f "$KIT/$file" ] || fail "missing $file"; done
bash -n "$KIT/prepare.sh" "$KIT/run.sh"
output="$($KIT/prepare.sh --dry-run)"
[[ "$output" == *"hf-mirror.com"* ]] || fail "HF mirror missing from dry run"
[[ "$output" == *"ghfast.top"* ]] || fail "GitHub mirror missing from dry run"
grep -q 'HF_ENDPOINT_OFFICIAL=https://huggingface.co' "$KIT/models.env" || fail "official HF fallback missing"
grep -q '^LLM_SMALL_REVISION=[0-9a-f]\{40\}$' "$KIT/models.env" || fail "small LLM revision not pinned"
grep -q '^LLM_LARGE_REVISION=[0-9a-f]\{40\}$' "$KIT/models.env" || fail "large LLM revision not pinned"
grep -q '^TTS_SMALL_REVISION=[0-9a-f]\{40\}$' "$KIT/models.env" || fail "small TTS revision not pinned"
grep -q '^TTS_LARGE_REVISION=[0-9a-f]\{40\}$' "$KIT/models.env" || fail "large TTS revision not pinned"
grep -q 'sha256sum -c' "$KIT/prepare.sh" || fail "tool checksum validation missing"
grep -q '^KWS_SHA256=[0-9a-f]\{64\}$' "$KIT/models.env" || fail "production KWS checksum missing"
grep -q '^PARAFORMER_SHA256=[0-9a-f]\{64\}$' "$KIT/models.env" || fail "production STT checksum missing"
grep -q '^SILERO_VAD_SHA256=[0-9a-f]\{64\}$' "$KIT/models.env" || fail "production VAD checksum missing"
grep -q '^TTS_FALLBACK_SHA256=[0-9a-f]\{64\}$' "$KIT/models.env" || fail "production TTS checksum missing"
grep -q 'docker inspect.*livekit-server livekit-agent' "$KIT/run.sh" || fail "LiveKit preservation check missing"
if grep -R -En '(token|password|secret)=' "$KIT"; then fail "possible credential embedded"; fi
echo 'PASS: S2S benchmark kit contract'
