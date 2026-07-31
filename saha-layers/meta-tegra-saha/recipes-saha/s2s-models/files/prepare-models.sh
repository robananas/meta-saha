#!/bin/sh
set -eu

src=${S2S_MODELS_DL_DIR:?}
dest=${1:?destination required}
rm -rf "$dest"
mkdir -p "$dest/kws" "$dest/stt" "$dest/tts"

verify() {
    file=$1
    expected=$2
    [ -s "$file" ] || {
        echo "ERROR: required verified S2S model artifact is absent: $file" >&2
        exit 1
    }
    printf '%s  %s\n' "$expected" "$file" | sha256sum -c - >/dev/null || {
        echo "ERROR: S2S model artifact checksum mismatch: $file" >&2
        exit 1
    }
}

verify "$src/$S2S_KWS_ARCHIVE" "$S2S_KWS_SHA256"
verify "$src/$S2S_VAD_FILE" "$S2S_VAD_SHA256"
verify "$src/$S2S_STT_ARCHIVE" "$S2S_STT_SHA256"
verify "$src/$S2S_TTS_ARCHIVE" "$S2S_TTS_SHA256"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

tar -xjf "$src/$S2S_KWS_ARCHIVE" -C "$tmp"
kws="$tmp/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
for file in encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx decoder-epoch-12-avg-2-chunk-16-left-64.onnx joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx tokens.txt; do
    [ -s "$kws/$file" ] || { echo "ERROR: KWS archive missing $file" >&2; exit 1; }
    cp "$kws/$file" "$dest/kws/$file"
done

cp "$src/$S2S_VAD_FILE" "$dest/silero_vad.onnx"

tar -xjf "$src/$S2S_STT_ARCHIVE" -C "$tmp"
stt="$tmp/sherpa-onnx-paraformer-zh-small-2024-03-09"
for file in model.int8.onnx tokens.txt; do
    [ -s "$stt/$file" ] || { echo "ERROR: STT archive missing $file" >&2; exit 1; }
    cp "$stt/$file" "$dest/stt/$file"
done
[ -s "$stt/test_wavs/0.wav" ] || { echo "ERROR: STT archive missing test_wavs/0.wav" >&2; exit 1; }
mkdir -p "$dest/stt/test_wavs"
cp "$stt/test_wavs/0.wav" "$dest/stt/test_wavs/0.wav"

tar -xjf "$src/$S2S_TTS_ARCHIVE" -C "$tmp"
tts="$tmp/sherpa-onnx-vits-zh-ll"
for file in model.onnx tokens.txt lexicon.txt date.fst phone.fst number.fst; do
    [ -s "$tts/$file" ] || { echo "ERROR: TTS archive missing $file" >&2; exit 1; }
    cp "$tts/$file" "$dest/tts/$file"
done
[ ! -d "$tts/dict" ] || cp -R "$tts/dict" "$dest/tts/dict"
