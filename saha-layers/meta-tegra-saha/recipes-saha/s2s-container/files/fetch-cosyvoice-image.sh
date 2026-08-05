#!/bin/sh
set -eu
output=$1
if [ ! -s "${COSYVOICE_LOCAL_TAR}" ]; then
    echo "Missing quality-gated CosyVoice image archive: ${COSYVOICE_LOCAL_TAR}" >&2
    exit 1
fi
cp --reflink=auto "${COSYVOICE_LOCAL_TAR}" "$output"
