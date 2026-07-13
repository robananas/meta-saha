#!/bin/sh
set -eu

src=$1
dest=$2
codes_src=$3

install -d "$dest"

for component in smartir xiaomi_home hacs; do
    install -d "${dest}/${component}"
    component_src="${src}/${component}/custom_components/${component}"
    if [ ! -d "$component_src" ]; then
        echo "Missing Home Assistant component source: ${component_src}" >&2
        exit 1
    fi
    cp -R --no-preserve=ownership "${component_src}/." "${dest}/${component}/"
    find "${dest}/${component}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
done

if [ -d "${codes_src}" ]; then
    install -d "${dest}/smartir/codes/climate" "${dest}/smartir/codes/media_player"
    if [ -d "${codes_src}/climate" ]; then
        cp -R --no-preserve=ownership "${codes_src}/climate/." "${dest}/smartir/codes/climate/"
    fi
    if [ -d "${codes_src}/media_player" ]; then
        cp -R --no-preserve=ownership "${codes_src}/media_player/." "${dest}/smartir/codes/media_player/"
    fi
fi
