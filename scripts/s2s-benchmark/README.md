# S2S Phase 1 post-flash benchmark kit

This directory prepares repeatable model-selection measurements after the board is flashed. It is not a production S2S implementation and does not modify, stop, or restart LiveKit.

## Isolation and prerequisites

Run as root on the Orin NX board. Everything is stored under `S2S_BENCH_ROOT` (default `/var/tmp/saha-s2s-benchmark`) and can be removed with `rm -rf "$S2S_BENCH_ROOT"`. The image must provide `curl`, `tar`, `bzip2`, `sha256sum`, `/usr/bin/time`, `find`, `tegrastats`, and the native CUDA 13.2 runtime. No package is installed into the base OS.

Use three controlled Mandarin PCM WAV files at 16 kHz mono: `mandarin-5s.wav`, `mandarin-15s.wav`, and `mandarin-30s.wav`. Put them in `$S2S_BENCH_ROOT/audio`, record their transcripts and SHA-256 values beside them, and do not compare accuracy across different recordings.

## Mirrors

Defaults target services commonly reachable in mainland China:

- Hugging Face: `https://hf-mirror.com` through `HF_ENDPOINT`.
- Python packages: Tsinghua Tuna `https://pypi.tuna.tsinghua.edu.cn/simple` through `PIP_INDEX_URL`.
- GitHub release assets: `https://ghfast.top` through `GITHUB_PROXY`.

All are overridable and contain no credentials. Public mirrors can lag, be unavailable, or serve stale/corrupt content. Pinned revisions plus SHA-256 verification reduce but do not eliminate supply-chain risk. `prepare.sh` retries official GitHub/Hugging Face sources if a mirror fails. For pip, retry explicitly with `PIP_INDEX_URL=https://pypi.org/simple`; do not combine public indexes with `--extra-index-url` because of dependency-confusion risk.

## Commands after flashing

Copy this directory to the board, then inspect commands without downloading:

```bash
cd /path/to/s2s-benchmark
HF_ENDPOINT=https://hf-mirror.com \
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
GITHUB_PROXY=https://ghfast.top \
S2S_BENCH_ROOT=/var/tmp/saha-s2s-benchmark \
./prepare.sh --dry-run
```

Download the pinned Paraformer and Qwen GGUF candidates and isolated ARM64 tools:

```bash
./prepare.sh
```

Run benchmarks while normal services remain active:

```bash
S2S_AUDIO_DIR=/var/tmp/saha-s2s-benchmark/audio ./run.sh
```

Capture longer thermal data only after all selected processes load and short tests pass safely:

```bash
timeout 1800 tegrastats --interval 1000 > /var/tmp/saha-s2s-benchmark/results/tegrastats-30m.txt
```

Do not run that endurance command for a partially functional stack.

## Required result interpretation

- Paraformer: derive RTF from elapsed/audio duration; report transcript against the fixed reference, peak RSS, and partial latency as unavailable for the offline binary.
- llama.cpp: report model file SHA-256/bytes, CUDA offload evidence, load time/peak RSS, prompt processing, generation tokens/s, and Chinese response quality. Start the OpenAI-compatible sidecar separately only after CLI CUDA validation: `llama-server -m MODEL -ngl 99 -c 4096 --host 127.0.0.1 --port 18080`.
- Qwen3-TTS: do not download either checkpoint until an isolated Python 3.12 + ARM64 CUDA PyTorch probe succeeds. Standard upstream PyTorch/FlashAttention/Triton wheels may be x86-only or mismatched with CUDA 13.2. If maintainability fails, benchmark the pinned sherpa-onnx VITS Chinese fallback on CPU.
- Faster Whisper: mark blocked unless a reproducible ARM64 CUDA CTranslate2 build compatible with CUDA 13.2 exists. Do not report CPU Whisper numbers as CUDA numbers.
- Combined residency: record baseline/loaded `free -b`, each process peak RSS, tegrastats RAM/GPU/temperature/power, and preserve at least 3 GiB available under normal services. A measured lock requires successful STT, LLM, TTS, and simultaneous residency; this kit alone is not a model lock.

## Cleanup

```bash
rm -rf /var/tmp/saha-s2s-benchmark
```

No board base-OS file, service unit, container, or LiveKit configuration should be changed by this workflow.
