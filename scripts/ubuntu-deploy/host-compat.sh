#!/usr/bin/env bash

roban_read_os() {
  source "${ROBAN_OS_RELEASE_FILE:-/etc/os-release}"
  ROBAN_HOST_OS_ID=${ID:-}
  ROBAN_HOST_VERSION_ID=${VERSION_ID:-}
  ROBAN_HOST_CODENAME=${VERSION_CODENAME:-}
}

roban_require_platform() {
  roban_read_os
  local expected_version=${ROBAN_EXPECTED_VERSION_ID:-24.04}
  local expected_codename=${ROBAN_EXPECTED_CODENAME:-noble}
  [[ $ROBAN_HOST_OS_ID == ubuntu && $ROBAN_HOST_VERSION_ID == "$expected_version" && $ROBAN_HOST_CODENAME == "$expected_codename" ]] || {
    printf 'Ubuntu %s %s required\n' "$expected_version" "$expected_codename" >&2
    return 1
  }
  case "$(uname -m)" in aarch64|arm64) ;; *) echo "ARM64 required" >&2; return 1 ;; esac
}

roban_version_ge() {
  dpkg --compare-versions "$1" ge "$2"
}

roban_check_common_commands() {
  local command
  for command in curl python3 nmcli bluetoothctl dbus-send sha256sum systemctl ss awk sed grep; do
    command -v "$command" >/dev/null || { echo "missing command: $command" >&2; return 1; }
  done
  if [[ ${ROBAN_SKIP_PYTHON_MODULE_CHECK:-0} != 1 ]]; then
    python3 -c 'import cryptography, dbus' 2>/dev/null || {
      echo "missing Ubuntu packages: python3-cryptography python3-dbus" >&2
      return 1
    }
  fi
  systemctl is-active --quiet NetworkManager
  systemctl is-active --quiet bluetooth
}

roban_check_docker_runtime() {
  command -v docker >/dev/null || { echo "Docker Engine is not installed" >&2; return 1; }
  docker compose version >/dev/null
  docker info >/dev/null
  local server_version compose_version
  server_version=$(docker version --format '{{.Server.Version}}')
  compose_version=$(docker compose version --short | sed 's/^v//')
  roban_version_ge "$server_version" "24.0" || { echo "Docker Engine 24.0 or newer required" >&2; return 1; }
  roban_version_ge "$compose_version" "2.20" || { echo "Docker Compose 2.20 or newer required" >&2; return 1; }
  if [[ ${ROBAN_REQUIRE_NVIDIA_RUNTIME:-1} == 1 ]]; then docker info --format '{{json .Runtimes}}' | grep -q 'nvidia'; fi
}

roban_check_target_ports() {
  local ports=${ROBAN_REQUIRED_TCP_PORTS:-"5580 7880 7881 7883 8000 8080 8123 8765 11435"}
  local port
  for port in $ports; do
    if ss -H -ltn "sport = :$port" 2>/dev/null | grep -q .; then
      echo "required TCP port is already in use: $port" >&2
      return 1
    fi
  done
}

roban_available_bytes() {
  df -PB1 "${ROBAN_STORAGE_PATH:-/var/lib}" | awk 'NR==2 {print $4}'
}

roban_check_disk_space() {
  local minimum=${ROBAN_MIN_FREE_BYTES:-12884901888}
  local available
  available=$(roban_available_bytes)
  [[ $available =~ ^[0-9]+$ ]] || { echo "unable to determine free disk space" >&2; return 1; }
  ((available >= minimum)) || {
    printf 'insufficient free space: need at least %s bytes, found %s\n' "$minimum" "$available" >&2
    return 1
  }
}

roban_verify_baseline_processes() {
  local baseline=$1 line pid command
  [[ -f $baseline/processes.txt ]] || { echo "process baseline is missing: $baseline" >&2; return 1; }
  while IFS= read -r line; do
    pid=${line%% *}; command=${line#* }
    [[ $pid =~ ^[0-9]+$ ]] || continue
    [[ $pid -eq $$ || $command =~ ^(ps|ssh|sshd|sudo|bash|sh|ros2)$ ]] && continue
    if [[ -r /proc/$pid/comm ]]; then
      [[ $(cat "/proc/$pid/comm") == "$command" ]] || { echo "protected process changed: $pid $command" >&2; return 1; }
    else
      echo "protected process stopped: $pid $command" >&2
      return 1
    fi
  done <"$baseline/processes.txt"
}

roban_capture_host_baseline() {
  local output=$1
  install -d -m 0700 "$output"
  dpkg-query -W >"$output/packages.txt" 2>/dev/null || true
  systemctl list-units --type=service --state=running --no-legend >"$output/running-services.txt" || true
  ss -H -lntup >"$output/listeners.txt" || true
  ps -eo pid=,comm= | grep -Ei 'ros|planner|mapping|driver|bridge|lidar|livox|foxglove|quest|canopen|chassis|terrain|pathFollower|rm_' >"$output/processes.txt" || : >"$output/processes.txt"
  find /etc/apt -maxdepth 2 -type f \( -name '*.list' -o -name '*.sources' \) -print0 | sort -z | xargs -0 -r sha256sum >"$output/apt-sources.sha256"
  if [[ -f /etc/docker/daemon.json ]]; then sha256sum /etc/docker/daemon.json >"$output/docker-daemon.sha256"; else : >"$output/docker-daemon.absent"; fi
}

roban_prepare_docker_ce_jammy() {
  if [[ ${ROBAN_FORCE_DOCKER_MISSING:-0} != 1 ]] && command -v docker >/dev/null; then
    roban_check_docker_runtime
    return 0
  fi
  [[ ${ROBAN_ALLOW_DOCKER_INSTALL:-0} == 1 ]] || { echo "Docker is missing; rerun Jammy installer with Docker preparation enabled" >&2; return 1; }
  if [[ -z ${ROBAN_DOCKER_GPG_FILE:-} ]]; then command -v gpg >/dev/null || { echo "missing command: gpg" >&2; return 1; }; fi
  local dry_run=${ROBAN_DRY_RUN:-0}
  local apt_root=${ROBAN_APT_ROOT:-/etc/apt}
  local keyring="$apt_root/keyrings/docker.gpg"
  local source_file="$apt_root/sources.list.d/docker.list"
  local apt_get=${ROBAN_APT_GET:-apt-get}
  local docker_apt_base=${ROBAN_DOCKER_APT_BASE_URL:-https://download.docker.com/linux/ubuntu}
  local architecture
  architecture=${ROBAN_DPKG_ARCHITECTURE:-$(dpkg --print-architecture)}
  [[ $architecture == arm64 ]] || { echo "Docker CE Jammy installation requires arm64" >&2; return 1; }
  if ((dry_run)); then
    echo "+ install Docker CE official Jammy repository and packages"
    return 0
  fi
  install -d -m 0755 "$apt_root/keyrings" "$apt_root/sources.list.d"
  local created_key=0 created_source=0
  cleanup_created_repo() { ((created_source == 0)) || rm -f "$source_file"; ((created_key == 0)) || rm -f "$keyring"; }
  if [[ -e $keyring && ! -s $keyring ]]; then rm -f "$keyring"; fi
  if [[ ! -e $keyring ]]; then
    if [[ -n ${ROBAN_DOCKER_GPG_FILE:-} ]]; then cp "$ROBAN_DOCKER_GPG_FILE" "$keyring"; else curl -fsSL "$docker_apt_base/gpg" | gpg --dearmor --yes -o "$keyring"; fi
    chmod 0644 "$keyring"; created_key=1
  fi
  if [[ ${ROBAN_SKIP_GPG_FINGERPRINT_CHECK:-0} != 1 ]]; then
    local fingerprint
    fingerprint=$(gpg --show-keys --with-colons "$keyring" 2>/dev/null | awk -F: '$1=="fpr" {print $10; exit}')
    [[ $fingerprint == 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]] || { echo "unexpected Docker signing key fingerprint" >&2; cleanup_created_repo; return 1; }
  fi
  if [[ ! -e $source_file ]]; then
    printf 'deb [arch=%s signed-by=%s] %s jammy stable\n' "$architecture" "$keyring" "$docker_apt_base" >"$source_file"; created_source=1
  elif ! grep -Fq "$docker_apt_base jammy stable" "$source_file"; then
    echo "existing Docker apt source is not the expected official Jammy source: $source_file" >&2
    return 1
  fi
  if ! "$apt_get" update; then cleanup_created_repo; return 1; fi
  local simulation
  simulation=$("$apt_get" -s install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)
  if printf '%s\n' "$simulation" | grep -Eq '^(Remv|Conf .*\[.*downgraded|Inst (nvidia-container-toolkit|network-manager|bluez|ros-))'; then
    echo "Docker CE installation would remove, downgrade, or replace protected host packages" >&2
    printf '%s\n' "$simulation" >&2
    cleanup_created_repo
    return 1
  fi
  if ! DEBIAN_FRONTEND=noninteractive "$apt_get" install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then cleanup_created_repo; return 1; fi
  if [[ ${ROBAN_SKIP_DOCKER_POSTCHECK:-0} != 1 ]]; then systemctl enable --now docker; roban_check_docker_runtime; fi
}
