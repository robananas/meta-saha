#!/usr/bin/env bash

roban_temp_write_daemon_config() {
  local path=$1 docker_root=$2 template=$3
  local expected
  expected=$(mktemp)
  sed "s|@DOCKER_ROOT@|$docker_root|g" "$template" >"$expected"
  if [[ -e $path ]]; then
    if ! cmp -s "$expected" "$path"; then rm -f "$expected"; echo "$path already exists with different content; refusing to overwrite" >&2; return 1; fi
    rm -f "$expected"
    return 0
  fi
  install -d -m 0755 "$(dirname "$path")" "$docker_root"
  install -m 0644 "$expected" "$path"
  rm -f "$expected"
}

roban_temp_cleanup_failed_deploy() {
  local launcher=${ROBAN_TEMP_LAUNCHER:-/usr/local/libexec/roban-app-temp}
  systemctl disable --now roban-temp-bt-wifi-provision roban-temp-mcp roban-temp-ha-bootstrap roban-temp-core roban-temp-board-status roban-temp-data-layout 2>/dev/null || true
  [[ ! -x $launcher ]] || "$launcher" down 2>/dev/null || true
}
