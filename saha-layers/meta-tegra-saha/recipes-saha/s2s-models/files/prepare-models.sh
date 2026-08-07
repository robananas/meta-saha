#!/bin/sh
set -eu

src=${S2S_MODELS_DL_DIR:?}
dest=${1:?destination required}
rm -rf "$dest"
mkdir -p "$dest/kws"

verify() {
    file=$1
    expected=$2
    [ -s "$file" ] || {
        echo "ERROR: required verified S2S base resource is absent: $file" >&2
        exit 1
    }
    printf '%s  %s\n' "$expected" "$file" | sha256sum -c - >/dev/null || {
        echo "ERROR: S2S base resource checksum mismatch: $file" >&2
        exit 1
    }
}

verify "$src/$S2S_KWS_ARCHIVE" "$S2S_KWS_SHA256"
verify "$src/$S2S_VAD_FILE" "$S2S_VAD_SHA256"
verify "$src/$S2S_WESPEAKER_FILE" "$S2S_WESPEAKER_SHA256"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

tar -xjf "$src/$S2S_KWS_ARCHIVE" -C "$tmp"
kws="$tmp/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
for file in encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx decoder-epoch-12-avg-2-chunk-16-left-64.onnx joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx tokens.txt; do
    [ -s "$kws/$file" ] || { echo "ERROR: KWS archive missing $file" >&2; exit 1; }
    cp "$kws/$file" "$dest/kws/$file"
done

cp "$src/$S2S_VAD_FILE" "$dest/silero_vad.onnx"
install -d -m 0750 "$dest/speaker/wespeaker-campp"
cp "$src/$S2S_WESPEAKER_FILE" "$dest/speaker/wespeaker-campp/campplus.onnx"
