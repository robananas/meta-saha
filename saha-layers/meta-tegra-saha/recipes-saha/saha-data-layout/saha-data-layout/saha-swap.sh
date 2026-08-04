#!/bin/sh
set -eu

swap_file=${SAHA_SWAP_FILE:-/data/swap/saha.swap}
size_gib=${SAHA_SWAP_SIZE_GIB:-16}
size_bytes=$((size_gib * 1024 * 1024 * 1024))

is_active() {
    awk -v file="$swap_file" 'NR > 1 && $1 == file { found = 1 } END { exit !found }' /proc/swaps
}

create_swap() {
    install -d -o root -g root -m 0700 "$(dirname "$swap_file")"
    current_size=$(stat -c %s "$swap_file" 2>/dev/null || printf 0)
    if [ "$current_size" -ne "$size_bytes" ]; then
        is_active && swapoff "$swap_file"
        rm -f "$swap_file"
        if ! fallocate -l "${size_gib}G" "$swap_file"; then
            dd if=/dev/zero of="$swap_file" bs=1M count=$((size_gib * 1024)) status=none
        fi
        chmod 0600 "$swap_file"
        mkswap "$swap_file" >/dev/null
    fi
    chmod 0600 "$swap_file"
}

case ${1:-} in
    start)
        mountpoint -q /data
        create_swap
        is_active || swapon --priority 10 "$swap_file"
        ;;
    stop)
        is_active && swapoff "$swap_file" || true
        ;;
    *)
        echo "Usage: $0 {start|stop}" >&2
        exit 2
        ;;
esac
