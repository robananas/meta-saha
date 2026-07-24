#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

contains() {
  local haystack=$1
  local needle=$2
  [[ "$haystack" == *"$needle"* ]] || fail "expected output to contain: $needle"
}

targets_output="$("$ROOT_DIR/scripts/saha-targets")"
contains "$targets_output" "orin-nx-16g-p3768"
contains "$targets_output" "p3768-0000-p3767-0000"
contains "$targets_output" "agx-thor-devkit"
contains "$targets_output" "jetson-agx-thor-devkit"
contains "$targets_output" "agx-orin-devkit"
contains "$targets_output" "jetson-agx-orin-devkit"
if [[ "$targets_output" == *"ros"* ]] || [[ "$targets_output" == *"ROS"* ]]; then
  fail "supported target list must not include ROS targets"
fi

dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768)"
contains "$dry_run_output" "DOCKER_CONFIG="
contains "$dry_run_output" "BUILDX_CONFIG="
contains "$dry_run_output" "docker image inspect"
contains "$dry_run_output" "meta-saha-yocto-builder:wrynose"
contains "$dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-jazzy.yml:kas/include/docker-images.yml"
contains "$dry_run_output" "/work/build/orin-nx-16g-p3768"
contains "$dry_run_output" "KAS_WORK_DIR=/work/build/orin-nx-16g-p3768"
contains "$dry_run_output" "GIT_HTTP_VERSION=HTTP/1.1"
contains "$dry_run_output" "GIT_CONFIG_COUNT=1"
contains "$dry_run_output" "GIT_CONFIG_KEY_0=http.version"
contains "$dry_run_output" "GIT_CONFIG_VALUE_0=HTTP/1.1"
contains "$dry_run_output" "SAHA_BB_NUMBER_THREADS=4"
contains "$dry_run_output" "SAHA_BB_NUMBER_PARSE_THREADS=4"
contains "$dry_run_output" "SAHA_PARALLEL_MAKE=-j\\ 4"
contains "$dry_run_output" "/work/downloads"
contains "$dry_run_output" "/work/sstate-cache"
if [[ "$dry_run_output" == *" -it "* ]]; then
  fail "non-interactive build command should not allocate a TTY"
fi

tuning_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    SAHA_BB_NUMBER_THREADS=2 \
    SAHA_BB_NUMBER_PARSE_THREADS=3 \
    SAHA_PARALLEL_MAKE="-j 6" \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$tuning_dry_run_output" "SAHA_BB_NUMBER_THREADS=2"
contains "$tuning_dry_run_output" "SAHA_BB_NUMBER_PARSE_THREADS=3"
contains "$tuning_dry_run_output" "SAHA_PARALLEL_MAKE=-j\\ 6"

lyrical_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    SAHA_ROS_DISTRO=lyrical \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$lyrical_dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-lyrical.yml:kas/include/docker-images.yml"
contains "$lyrical_dry_run_output" "/build/orin-nx-16g-p3768-ros-lyrical:/work/build/orin-nx-16g-p3768"

no_docker_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    HAVE_DOCKER_IMAGE=0 \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$no_docker_dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot-ros.yml:kas/include/ros-distro-jazzy.yml"
contains "$no_docker_dry_run_output" "/build/orin-nx-16g-p3768-robot-ros:/work/build/orin-nx-16g-p3768"
if [[ "$no_docker_dry_run_output" == *"docker-images.yml"* ]]; then
  fail "HAVE_DOCKER_IMAGE=0 must omit the docker images kas include"
fi

no_ros_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    HAVE_ROS=0 \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$no_ros_dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot-docker.yml:kas/include/no-ros.yml:kas/include/docker-images.yml"
contains "$no_ros_dry_run_output" "/build/orin-nx-16g-p3768-robot-docker:/work/build/orin-nx-16g-p3768"
if [[ "$no_ros_dry_run_output" == *"ros-distro-"* ]]; then
  fail "HAVE_ROS=0 must omit ros-distro kas includes"
fi

slim_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    HAVE_DOCKER_IMAGE=0 \
    HAVE_ROS=0 \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$slim_dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot-base.yml:kas/include/no-ros.yml"
contains "$slim_dry_run_output" "/build/orin-nx-16g-p3768-robot-base:/work/build/orin-nx-16g-p3768"
if [[ "$slim_dry_run_output" == *"docker-images.yml"* ]] ||
   [[ "$slim_dry_run_output" == *"ros-distro-"* ]]; then
  fail "slim build must omit docker images and ros-distro kas includes"
fi

if SAHA_ROBOT_IMAGE=maybe "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768 >/tmp/saha-invalid-robot-image.out 2>&1; then
  fail "invalid SAHA_ROBOT_IMAGE values must be rejected"
fi
grep -q 'Unsupported robot image profile' /tmp/saha-invalid-robot-image.out ||
  fail "invalid SAHA_ROBOT_IMAGE values must report a clear error"

robot_base_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    SAHA_ROBOT_IMAGE=robot-base \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$robot_base_dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot-base.yml:kas/include/no-ros.yml"
contains "$robot_base_dry_run_output" "/build/orin-nx-16g-p3768-robot-base:/work/build/orin-nx-16g-p3768"

robot_images_output="$("$ROOT_DIR/scripts/saha-robot-images")"
contains "$robot_images_output" "robot-base"
contains "$robot_images_output" "saha-image-robot-base"
contains "$robot_images_output" "saha-image-robot-docker"

if HAVE_ROS=maybe "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768 >/tmp/saha-invalid-ros-flag.out 2>&1; then
  fail "invalid HAVE_ROS values must be rejected"
fi
grep -q 'Unsupported HAVE_ROS value' /tmp/saha-invalid-ros-flag.out ||
  fail "invalid HAVE_ROS values must report a clear error"

if HAVE_DOCKER_IMAGE=maybe "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768 >/tmp/saha-invalid-docker.out 2>&1; then
  fail "invalid HAVE_DOCKER_IMAGE values must be rejected"
fi
grep -q 'Unsupported HAVE_DOCKER_IMAGE value' /tmp/saha-invalid-docker.out ||
  fail "invalid HAVE_DOCKER_IMAGE values must report a clear error"

! grep -q 'kas/include/docker-images.yml' "$ROOT_DIR/kas/include/base.yml" ||
  fail "docker images kas include must be selected by HAVE_DOCKER_IMAGE, not base.yml"

if [ ! -f "$ROOT_DIR/kas/include/docker-images.yml" ]; then
  fail "docker images kas include must exist"
fi
grep -q 'IMAGE_ROOTFS_EXTRA_SPACE:append:pn-saha-image-robot' \
  "$ROOT_DIR/kas/include/docker-images.yml" ||
  fail "docker images kas include must reserve rootfs space for robot images"
grep -q 'IMAGE_ROOTFS_EXTRA_SPACE:append:pn-saha-image-robot-docker' \
  "$ROOT_DIR/kas/include/docker-images.yml" ||
  fail "docker images kas include must reserve rootfs space for robot-docker"
grep -q 'packagegroup-saha-docker-images' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot.bb" ||
  fail "saha-image-robot must install the docker images packagegroup"
grep -q 'packagegroup-saha-docker-images' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot-docker.bb" ||
  fail "saha-image-robot-docker must install the docker images packagegroup"
grep -q 'saha-docker-compose' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must install docker compose launcher"
grep -q 'roban-app' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must install roban-app image recipe"
grep -q 'docker compose' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.sh" ||
  fail "docker compose launcher must start the stack with docker compose"
grep -q '/opt/roban/compose/compose.yaml' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose.bb" ||
  fail "docker compose launcher must install compose.yaml under /opt/roban/compose"
grep -q 'ghcr.io/matter-js/python-matter-server:arm64' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml" ||
  fail "compose stack must use the arm64 Matter Server image"
grep -q -- '--bluetooth-adapter' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml" ||
  fail "Matter Server must enable board Bluetooth commissioning"
grep -q -- '--primary-interface' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml" ||
  fail "Matter Server must bind link-local Matter traffic to the board WiFi interface"
grep -q 'roban-workflow-api:arm64' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml" ||
  fail "compose stack must include roban-workflow-api"
grep -q 'roban-workflow-api.tar' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/roban-app/roban-app/fetch-image.sh" ||
  fail "roban-app fetch script must support local tarball cache"
grep -q 'saha-livekit-server-container-image' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must preload LiveKit Server"
grep -q 'saha-livekit-agent-image' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must preload local LiveKit Agent"
grep -q 'livekit/livekit-server:v1.13.4' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml" ||
  fail "compose stack must include pinned LiveKit Server"
grep -q 'livekit-agent:arm64' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml" ||
  fail "compose stack must include local ARM64 LiveKit Agent"
grep -q 'ensure_livekit_credentials' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.sh" ||
  fail "compose launcher must generate persistent LiveKit credentials"
grep -q 'livekit-agent.tar' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/livekit-agent/files/fetch-image.sh" ||
  fail "LiveKit Agent recipe must support local tarball cache"
HA_CONFIG_RECIPE="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config.bb"
[ -f "$HA_CONFIG_RECIPE" ] ||
  fail "saha-homeassistant-config recipe must exist"
grep -q 'saha-homeassistant-config' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must install homeassistant config template"
grep -q 'SmartIR' "$HA_CONFIG_RECIPE" ||
  fail "homeassistant config recipe must fetch SmartIR"
grep -q 'ha_xiaomi_home' "$HA_CONFIG_RECIPE" ||
  fail "homeassistant config recipe must fetch Xiaomi Home"
grep -q 'SRCREV_FORMAT = "smartir_xiaomi_hacs"' "$HA_CONFIG_RECIPE" ||
  fail "homeassistant config recipe must set SRCREV_FORMAT for multiple git fetchers"
grep -q 'hacs' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config/install-custom-components.sh" ||
  fail "homeassistant config install script must install HACS"
grep -q 'packages/tv_power.yaml' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config.bb" ||
  fail "homeassistant config recipe must install tv_power package"
grep -q 'ui-lovelace.yaml' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config.bb" ||
  fail "homeassistant config recipe must install ui-lovelace.yaml"
grep -q 'hitachi_ac_rm4' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config/configuration.yaml" ||
  fail "default homeassistant config must include SmartIR climate device"
grep -q 'meeting_room_tv_02' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config/configuration.yaml" ||
  fail "default homeassistant config must include SmartIR media_player device"
grep -q 'saha_matter:' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config/configuration.yaml" ||
  fail "default homeassistant config must bootstrap Matter"
grep -q 'ws://127.0.0.1:5580/ws' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-config/saha-homeassistant-config/configuration.yaml" ||
  fail "Matter bootstrap must use the board-local Matter Server"
grep -q 'custom-components/saha_matter/__init__.py' "$HA_CONFIG_RECIPE" ||
  fail "homeassistant config recipe must install the Matter bootstrap integration"
grep -q '1084.json' "$HA_CONFIG_RECIPE" ||
  fail "homeassistant config recipe must bundle SmartIR climate code 1084"
grep -q '1380.json' "$HA_CONFIG_RECIPE" ||
  fail "homeassistant config recipe must bundle SmartIR media_player code 1380"
grep -q 'seed_homeassistant_config' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.sh" ||
  fail "docker compose launcher must seed homeassistant config on first boot"
grep -q 'saha-bt-wifi-provision' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-bluetooth.bb" ||
  fail "bluetooth packagegroup must install saha-bt-wifi-provision"
BT_WIFI_PROVISION="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision.bb"
[ -f "$BT_WIFI_PROVISION" ] ||
  fail "saha-bt-wifi-provision recipe must exist"
grep -q 'a0a0ff10-0000-1000-8000-00805f9b34fb' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/GATT.md" ||
  fail "GATT API doc must define the WiFi provision service UUID"
grep -q 'nmcli' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/wifi_manager.py" ||
  fail "WiFi provision service must integrate with nmcli"
grep -q 'dbus-glib' \
  "$BT_WIFI_PROVISION" ||
  fail "saha-bt-wifi-provision must depend on dbus-glib for dbus main loop integration"
grep -q 'python3-ctypes' \
  "$BT_WIFI_PROVISION" ||
  fail "saha-bt-wifi-provision must depend on python3-ctypes for glib main loop integration"
grep -q 'python3-json' \
  "$BT_WIFI_PROVISION" ||
  fail "saha-bt-wifi-provision must depend on python3-json for WiFi command payloads"
grep -q 'python3-threading' \
  "$BT_WIFI_PROVISION" ||
  fail "saha-bt-wifi-provision must depend on python3-threading for BLE command queue handling"
grep -q 'python3-subprocess' \
  "$BT_WIFI_PROVISION" &&
  fail "saha-bt-wifi-provision must not depend on python3-subprocess on wrynose; subprocess is in python3-core"
grep -q 'setup_dbus_main_loop' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/gatt_server.py" ||
  fail "gatt server must install a dbus main loop before exporting objects"
if grep -Eq 'RegisterAgent|NoInputNoOutput|encrypt-(read|write)' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/gatt_server.py"; then
  fail "Secure Protocol v2 must not depend on BlueZ pairing or encrypted flags"
fi
grep -Fq '"Pairable", dbus.Boolean(False)' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/gatt_server.py" ||
  fail "Secure Protocol v2 must disable BlueZ pairing"
grep -Fq '"Discoverable", dbus.Boolean(False)' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/gatt_server.py" ||
  fail "gatt server must keep classic Bluetooth non-discoverable"
grep -q 'python3-cryptography' "$BT_WIFI_PROVISION" ||
  fail "Secure Protocol v2 must install python3-cryptography"
grep -q 'secure_protocol.py' "$BT_WIFI_PROVISION" ||
  fail "Secure Protocol v2 implementation must be packaged"
grep -q 'UMask=0077' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/saha-bt-wifi-provision.service" ||
  fail "WiFi provisioning service must use a restrictive umask"
grep -q '^StateDirectory=saha$' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/saha-bt-wifi-provision.service" ||
  fail "WiFi provisioning service must create and own /var/lib/saha before namespace setup"
grep -q '^StateDirectoryMode=0700$' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/saha-bt-wifi-provision.service" ||
  fail "WiFi provisioning state directory must be private"
grep -q 'session_state.py' "$BT_WIFI_PROVISION" ||
  fail "request tombstone and provisioning owner state must be packaged"
grep -q 'HA_CREDENTIALS_UNAVAILABLE' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/gatt_server.py" ||
  fail "BLE provisioning must classify temporarily unavailable HA credentials for App retry"
grep -q 'development-ble-device-ed25519.key' "$BT_WIFI_PROVISION" ||
  fail "development image must bundle the BLE device identity"
grep -q 'development-ble-app-keyring.json' "$BT_WIFI_PROVISION" ||
  fail "development image must bundle the trusted App keyring"
grep -q 'install -m 0600.*development-ble-device-ed25519.key' "$BT_WIFI_PROVISION" ||
  fail "bundled BLE device private key must install with mode 0600"
grep -q 'saha-homeassistant-container-image' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must include the Home Assistant image recipe"
grep -q 'saha-matter-server-container-image' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-docker-images.bb" ||
  fail "docker images packagegroup must include the Matter Server image recipe"
grep -q 'homeassistant-container.tar' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-container/saha-homeassistant-container-image/fetch-image.sh" ||
  fail "Home Assistant fetch script must support local tarball cache"
grep -q 'matter-server-container.tar' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/matter-server-container/saha-matter-server-container-image/fetch-image.sh" ||
  fail "Matter Server fetch script must support local tarball cache"
grep -q 'multi-user.target.wants/saha-docker-compose.service' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose.bb" ||
  fail "docker compose launcher must enable systemd service at install time"
grep -q 'wait_for_valid_clock' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.sh" ||
  fail "docker compose launcher must reject an invalid system clock"
grep -q 'bootstrap_clock_from_https' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.sh" ||
  fail "docker compose launcher must bootstrap time when UDP NTP is unavailable"
grep -q 'systemd-timesyncd.service time-sync.target' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.service" ||
  fail "docker compose service must start after system time synchronization"
grep -q 'system clock is invalid; trying immediate HTTPS bootstrap' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/saha-docker-compose.sh" ||
  fail "docker compose launcher must attempt HTTPS time bootstrap without an NTP delay"
grep -q 'disable_conflicting_networkd_wait_online' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-common.inc" ||
  fail "Saha images must disable systemd-networkd wait-online when NetworkManager owns networking"
if grep -q 'restart: unless-stopped' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml"; then
  fail "containers must not bypass the clock gate during Docker daemon startup"
fi
grep -q '^Wants=saha-docker-compose.service$' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.service" ||
  fail "Home Assistant bootstrap must survive an initial compose clock-gate failure"
if grep -q '^Requires=saha-docker-compose.service$' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.service"; then
  fail "Home Assistant bootstrap must not be skipped permanently when compose retries"
fi
grep -q 'status_code != 400' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.py" ||
  fail "Home Assistant bootstrap must recover a rejected refresh credential"
grep -q 'credentials_from_recovery' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.py" ||
  fail "Home Assistant bootstrap must persist recovered credentials"
grep -q 'exc.status_code == 404' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.py" ||
  fail "Home Assistant bootstrap must treat completed onboarding 404 as ready"

proxy_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    SAHA_LOAD_ZSHRC_PROXY=0 \
    HTTP_PROXY=http://proxy.example.invalid:3128 \
    no_proxy=localhost,127.0.0.1 \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$proxy_dry_run_output" "--build-arg HTTP_PROXY"
contains "$proxy_dry_run_output" "--build-arg no_proxy"
contains "$proxy_dry_run_output" "-e HTTP_PROXY"
contains "$proxy_dry_run_output" "-e no_proxy"
if [[ "$proxy_dry_run_output" == *"proxy.example.invalid"* ]]; then
  fail "dry-run output must not expose proxy values"
fi

no_proxy_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    SAHA_NO_PROXY=1 \
    HTTP_PROXY=http://proxy.example.invalid:3128 \
    HTTPS_PROXY=http://proxy.example.invalid:3128 \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$no_proxy_dry_run_output" "-e HTTP_PROXY="
contains "$no_proxy_dry_run_output" "-e HTTPS_PROXY="
contains "$no_proxy_dry_run_output" "-e http_proxy="
contains "$no_proxy_dry_run_output" "-e https_proxy="
if [[ "$no_proxy_dry_run_output" == *"--build-arg HTTP_PROXY"* ]] ||
   [[ "$no_proxy_dry_run_output" == *"proxy.example.invalid"* ]]; then
  fail "SAHA_NO_PROXY must disable proxy propagation and hide proxy values"
fi

loopback_proxy_dry_run_output="$(
  env \
    SAHA_DRY_RUN=1 \
    SAHA_LOAD_ZSHRC_PROXY=0 \
    HTTPS_PROXY=http://127.0.0.1:3128 \
    all_proxy=socks5://localhost:1080 \
    "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768
)"
contains "$loopback_proxy_dry_run_output" "--network host"
contains "$loopback_proxy_dry_run_output" "--build-arg HTTPS_PROXY"
contains "$loopback_proxy_dry_run_output" "-e HTTPS_PROXY"
if [[ "$loopback_proxy_dry_run_output" == *"127.0.0.1"* ]] ||
   [[ "$loopback_proxy_dry_run_output" == *"localhost:1080"* ]]; then
  fail "loopback proxy dry-run output must not expose proxy values"
fi

if command -v zsh >/dev/null 2>&1; then
  tmp_home="$(mktemp -d)"
  cat >"$tmp_home/.zshrc" <<'ZSHRC'
export HTTPS_PROXY=http://zsh-proxy.example.invalid:3128
export all_proxy=socks5://zsh-socks.example.invalid:1080
ZSHRC
  zsh_proxy_output="$(
    env -i \
      PATH="$PATH" \
      HOME="$tmp_home" \
      SAHA_DRY_RUN=1 \
      "$ROOT_DIR/scripts/saha-build" agx-orin-devkit
  )"
  contains "$zsh_proxy_output" "--build-arg HTTPS_PROXY"
  contains "$zsh_proxy_output" "--build-arg all_proxy"
  contains "$zsh_proxy_output" "-e HTTPS_PROXY"
  contains "$zsh_proxy_output" "-e all_proxy"
  if [[ "$zsh_proxy_output" == *"zsh-proxy.example.invalid"* ]] ||
     [[ "$zsh_proxy_output" == *"zsh-socks.example.invalid"* ]]; then
    fail "zshrc-loaded proxy values must not appear in dry-run output"
  fi
  zsh_proxy_with_no_proxy_output="$(
    env -i \
      PATH="$PATH" \
      HOME="$tmp_home" \
      NO_PROXY=localhost \
      SAHA_DRY_RUN=1 \
      "$ROOT_DIR/scripts/saha-build" agx-orin-devkit
  )"
  contains "$zsh_proxy_with_no_proxy_output" "--build-arg HTTPS_PROXY"
  contains "$zsh_proxy_with_no_proxy_output" "--build-arg NO_PROXY"
  rm -rf "$tmp_home"
fi

if "$ROOT_DIR/scripts/saha-build" invalid-target >/tmp/saha-invalid-target.out 2>&1; then
  fail "invalid target unexpectedly succeeded"
fi
contains "$(cat /tmp/saha-invalid-target.out)" "Unsupported target: invalid-target"

if SAHA_ROS_DISTRO=humble "$ROOT_DIR/scripts/saha-build" orin-nx-16g-p3768 >/tmp/saha-invalid-ros.out 2>&1; then
  fail "invalid ROS distro unexpectedly succeeded"
fi
contains "$(cat /tmp/saha-invalid-ros.out)" "Unsupported ROS distro: humble"
contains "$(cat /tmp/saha-invalid-ros.out)" "Supported ROS distros:"

for ignored in ".docker-cache" "build" "downloads" "sstate-cache" "repos"; do
  grep -qxF "$ignored" "$ROOT_DIR/.dockerignore" || fail ".dockerignore missing $ignored"
done

grep -A4 '^  bitbake:' "$ROOT_DIR/kas/include/repos-wrynose.yml" |
  grep -qxF '    branch: "2.18"' ||
  fail "bitbake must use the Wrynose-compatible 2.18 branch"

grep -A3 '^  meta-saha:' "$ROOT_DIR/kas/include/repos-wrynose.yml" |
  grep -qxF '    path: /work/meta-saha' ||
  fail "local meta-saha repo path must match the Docker mount point"

if grep -q '^  meta-ros:' "$ROOT_DIR/kas/include/repos-wrynose.yml"; then
  fail "base Wrynose repo graph must not hard-code one ROS distro layer"
fi
for ros_distro in jazzy lyrical; do
  ros_include="$ROOT_DIR/kas/include/ros-distro-$ros_distro.yml"
  [ -f "$ros_include" ] || fail "ROS distro kas include missing: $ros_include"
  grep -A10 '^  meta-ros:' "$ros_include" |
    grep -qxF '    url: https://github.com/ros/meta-ros.git' ||
    fail "ROS distro kas include must define meta-ros: $ros_include"
  grep -A10 '^  meta-ros:' "$ros_include" |
    grep -qxF '    branch: wrynose' ||
    fail "ROS distro kas include must pin the Wrynose branch: $ros_include"
  grep -A10 '^  meta-ros:' "$ros_include" |
    grep -qxF "      meta-ros2-$ros_distro:" ||
    fail "ROS distro kas include must select meta-ros2-$ros_distro"
done
grep -q 'ROS_WORLD_SKIP_GROUPS:append = " zenoh"' "$ROOT_DIR/kas/include/ros-distro-lyrical.yml" ||
  fail "Lyrical builds must skip the zenoh group unless meta-zenoh is added"

grep -q 'EXTRA_IMAGE_FEATURES ?= "empty-root-password allow-root-login"' "$ROOT_DIR/kas/include/base.yml" ||
  fail "Wrynose image features must not use removed debug-tweaks alias"

OPENSSH_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/openssh/openssh_%.bbappend"
[ -f "$OPENSSH_APPEND" ] ||
  fail "openssh bbappend must exist for SSH root empty-password access"
grep -q 'PermitEmptyPasswords yes' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/openssh/openssh/99-saha-root-empty-password.conf" ||
  fail "OpenSSH must explicitly permit empty passwords for root SSH access"

grep -q 'BB_HASHSERVE_DB_DIR ?= "${SSTATE_DIR}"' "$ROOT_DIR/kas/include/base.yml" ||
  fail "shared sstate builds should also share hash equivalence database"

grep -q 'PREFERRED_PROVIDER_edk2-nvidia-standalone-mm = "edk2-nvidia-standalone-mm-prebuilt"' "$ROOT_DIR/kas/include/base.yml" ||
  fail "default BSP build should use OE4T prebuilt standalone-mm provider"

grep -A2 '^target:$' "$ROOT_DIR/kas/include/base.yml" |
  grep -qxF '  - saha-image-robot' ||
  fail "default kas build target must be saha-image-robot"

grep -q 'Build a Saha robot image' "$ROOT_DIR/scripts/saha-build" ||
  fail "saha-build help must describe robot image profiles"

[ -f "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot.bb" ] ||
  fail "saha-image-robot recipe must exist"
[ -f "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot-base.bb" ] ||
  fail "saha-image-robot-base recipe must exist"
[ -f "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot-ros.bb" ] ||
  fail "saha-image-robot-ros recipe must exist"
[ -f "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot-docker.bb" ] ||
  fail "saha-image-robot-docker recipe must exist"
grep -q 'packagegroup-saha-ros2' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot.bb" ||
  fail "saha-image-robot must install the Saha ROS 2 packagegroup"
grep -q 'packagegroup-saha-ros2' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot-ros.bb" ||
  fail "saha-image-robot-ros must install the Saha ROS 2 packagegroup"
grep -q 'packagegroup-saha-ros2' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot-base.bb" &&
  fail "saha-image-robot-base must not install ROS 2"
[ -f "$ROOT_DIR/kas/include/image-profile-robot-base.yml" ] ||
  fail "robot-base kas profile must exist"
grep -q 'saha-image-robot-base' "$ROOT_DIR/kas/include/image-profile-robot-base.yml" ||
  fail "robot-base kas profile must target saha-image-robot-base"
[ -f "$ROOT_DIR/kas/include/no-ros.yml" ] ||
  fail "no-ros kas include must exist for profiles without ROS 2"

ROS2_PACKAGEGROUP="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-ros/packagegroups/packagegroup-saha-ros2.bb"
[ -f "$ROS2_PACKAGEGROUP" ] ||
  fail "Saha ROS 2 packagegroup must exist"
grep -q 'recipes-bsp/\*/\*' "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/layer.conf" ||
  fail "tegra-saha layer must enumerate non-ROS recipe directories explicitly"
grep -q 'BBFILES_DYNAMIC' "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/layer.conf" ||
  fail "tegra-saha layer must use BBFILES_DYNAMIC for recipes-ros"
grep -q 'ros2-layer:${LAYERDIR}/recipes-ros' "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/layer.conf" ||
  fail "recipes-ros must load only when ros2-layer is present"
grep -q 'ros-base' "$ROS2_PACKAGEGROUP" ||
  fail "Saha ROS 2 packagegroup must install ROS 2 ros-base"
grep -q 'ros2cli-common-extensions' "$ROS2_PACKAGEGROUP" ||
  fail "Saha ROS 2 packagegroup must install ROS 2 CLI extensions"
RMW_IMPLEMENTATION_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-ros/rmw-implementation/rmw-implementation_%.bbappend"
[ -f "$RMW_IMPLEMENTATION_APPEND" ] ||
  fail "Saha rmw-implementation bbappend must exist for Lyrical without meta-zenoh"
grep -q 'ROS_BUILD_DEPENDS:remove = "rmw-zenoh-cpp"' "$RMW_IMPLEMENTATION_APPEND" ||
  fail "Lyrical rmw-implementation must not require rmw-zenoh-cpp without meta-zenoh"
ROS_CORE_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-ros/variants/ros-core_%.bbappend"
[ -f "$ROS_CORE_APPEND" ] ||
  fail "Saha ros-core bbappend must exist for Lyrical without meta-zenoh"
grep -q "d.getVar('ROS_DISTRO') == 'lyrical'" "$ROS_CORE_APPEND" ||
  fail "ros-core launch-testing-ros removal must be limited to Lyrical"
grep -q "launch-testing-ros" "$ROS_CORE_APPEND" ||
  fail "Lyrical ros-core must not require skipped launch-testing-ros"
AMENT_CMAKE_ROS_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-ros/ament-cmake-ros/ament-cmake-ros_%.bbappend"
[ -f "$AMENT_CMAKE_ROS_APPEND" ] ||
  fail "Saha ament-cmake-ros bbappend must exist for Lyrical without meta-zenoh"
grep -q "d.getVar('ROS_DISTRO') == 'lyrical'" "$AMENT_CMAKE_ROS_APPEND" ||
  fail "ament-cmake-ros fixture removal must be limited to Lyrical"
grep -q "rmw-test-fixture-implementation" "$AMENT_CMAKE_ROS_APPEND" ||
  fail "Lyrical ament-cmake-ros must not require skipped rmw-test-fixture-implementation"

PROFILE_PACKAGEGROUP="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-core/packagegroups/packagegroup-core-tools-profile.bbappend"
[ -f "$PROFILE_PACKAGEGROUP" ] ||
  fail "profiling packagegroup override must exist"
grep -qxF 'LTTNGTOOLS = "lttng-tools"' "$PROFILE_PACKAGEGROUP" ||
  fail "profiling tools must not pull unsupported lttng kernel module"
LTTNG_TOOLS_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-support/lttng/lttng-tools_%.bbappend"
[ -f "$LTTNG_TOOLS_APPEND" ] ||
  fail "lttng-tools bbappend must exist"
grep -qxF 'LTTNGMODULES = ""' "$LTTNG_TOOLS_APPEND" ||
  fail "lttng-tools ptest dependencies must not pull unsupported lttng kernel module"

grep -qxF 'hostname = "soybean"' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-core/base-files/base-files_%.bbappend" ||
  fail "base-files must set the device hostname to soybean"

USB_DEVICE_MODE_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-bsp/l4t-usb-device-mode/l4t-usb-device-mode.bbappend"
[ -f "$USB_DEVICE_MODE_APPEND" ] ||
  fail "l4t-usb-device-mode bbappend must exist"
grep -q 'multi-user.target.wants/usb-gadget.target' "$USB_DEVICE_MODE_APPEND" ||
  fail "USB gadget target must be wanted by multi-user.target for default USB network access"
grep -q 'saha-usb-role-device' "$USB_DEVICE_MODE_APPEND" ||
  fail "USB gadget setup must install the Saha USB role helper"
USB_ROLE_HELPER="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-bsp/l4t-usb-device-mode/l4t-usb-device-mode/saha-usb-role-device"
[ -f "$USB_ROLE_HELPER" ] ||
  fail "Saha USB role helper must exist"
grep -q '/sys/class/usb_role/usb2-0-role-switch/role' "$USB_ROLE_HELPER" ||
  fail "Saha USB role helper must target the Orin USB2-0 role switch"
grep -q 'echo device >' "$USB_ROLE_HELPER" ||
  fail "Saha USB role helper must force device role before gadget start"

NETWORK_PACKAGEGROUP="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-network.bb"
[ -f "$NETWORK_PACKAGEGROUP" ] ||
  fail "network packagegroup must exist"
grep -q 'networkmanager-nmcli' "$NETWORK_PACKAGEGROUP" ||
  fail "network packagegroup must install nmcli"
grep -q 'networkmanager-wifi' "$NETWORK_PACKAGEGROUP" ||
  fail "network packagegroup must install WiFi support"
NETWORKMANAGER_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/networkmanager/networkmanager_%.bbappend"
[ -f "$NETWORKMANAGER_APPEND" ] ||
  fail "NetworkManager bbappend must exist"
grep -q 'except:type:wifi' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/networkmanager/networkmanager/99-saha-unmanaged-devices.conf" ||
  fail "NetworkManager must leave USB gadget interfaces to systemd-networkd"
grep -q 'packagegroup-saha-network' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-common.inc" ||
  fail "default Saha images must include network packagegroup"
grep -q 'wifi' "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/distro/tegra-saha.conf" ||
  fail "tegra-saha distro must enable wifi DISTRO_FEATURE"

BLUETOOTH_PACKAGEGROUP="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-bluetooth.bb"
[ -f "$BLUETOOTH_PACKAGEGROUP" ] ||
  fail "bluetooth packagegroup must exist"
grep -q 'bluez5' "$BLUETOOTH_PACKAGEGROUP" ||
  fail "bluetooth packagegroup must install bluez5"
grep -q 'tegra-bluetooth' "$BLUETOOTH_PACKAGEGROUP" ||
  fail "bluetooth packagegroup must install tegra-bluetooth"
grep -qxF 'RDEPENDS:${PN}:append:p3768-0000-p3767-0000 = " kernel-module-rtk-btusb"' "$BLUETOOTH_PACKAGEGROUP" ||
  fail "P3768 Bluetooth packagegroup must install the vendor rtk_btusb module"
if grep -Eq '(^|[[:space:]"-])kernel-module-btusb([[:space:]"-]|$)' "$BLUETOOTH_PACKAGEGROUP"; then
  fail "P3768 Bluetooth packagegroup must not install upstream btusb"
fi
[ ! -e "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/ble-identity" ] ||
  fail "unused BLE identity recipe must be removed"
if rg -n 'saha-ble-identity|static-addr' "$ROOT_DIR/saha-layers" >/tmp/saha-removed-ble-identity.out; then
  cat /tmp/saha-removed-ble-identity.out >&2
  fail "layer metadata must not retain the identity service or static address setup"
fi
BLUEZ_APPEND="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5_%.bbappend"
[ -f "$BLUEZ_APPEND" ] ||
  fail "bluez5 bbappend must exist"
grep -q 'Roban-Bluetooth' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5/main.conf" ||
  fail "bluez5 must set the Roban-Bluetooth adapter name"
grep -Eq '^ReverseServiceDiscovery[[:space:]]*=[[:space:]]*false$' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5/main.conf" ||
  fail "BlueZ peripheral must disable reverse GATT discovery to avoid Android pairing prompts"
grep -q 'Experimental = true' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5/main.conf" ||
  fail "bluez5 must enable experimental GATT support"
grep -q 'ControllerMode = le' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5/main.conf" ||
  fail "bluez5 must run the controller in LE-only mode"
grep -q 'Privacy = device' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5/main.conf" ||
  fail "bluez5 must enable device privacy"
BLUEZ_SERVICE_DROPIN="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-connectivity/bluez/bluez5/bluetooth.service.d/saha-experimental.conf"
if grep -Eq '^(Requires|After)=.*ble-identity' "$BLUEZ_SERVICE_DROPIN"; then
  fail "bluetoothd must not depend on a BLE identity service"
fi
grep -q 'Wants=saha-bt-wifi-provision.service' "$BLUEZ_SERVICE_DROPIN" ||
  fail "bluetoothd must pull in WiFi provisioning"
grep -q 'Before=saha-bt-wifi-provision.service' "$BLUEZ_SERVICE_DROPIN" ||
  fail "bluetoothd must start before WiFi provisioning"
BT_WIFI_PROVISION_SERVICE="$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision/saha-bt-wifi-provision.service"
grep -q '^Requires=bluetooth.service$' "$BT_WIFI_PROVISION_SERVICE" ||
  fail "WiFi provisioning must require bluetooth.service"
grep -q '^BindsTo=bluetooth.service$' "$BT_WIFI_PROVISION_SERVICE" ||
  fail "WiFi provisioning must stop when bluetooth.service disappears"
grep -q '^PartOf=bluetooth.service$' "$BT_WIFI_PROVISION_SERVICE" ||
  fail "WiFi provisioning must follow Bluetooth lifecycle jobs"
grep -q '^After=.*NetworkManager-wait-online.service' "$BT_WIFI_PROVISION_SERVICE" ||
  fail "WiFi provisioning must wait for NetworkManager connectivity before exporting Matter credentials"
grep -q '^Wants=.*NetworkManager-wait-online.service' "$BT_WIFI_PROVISION_SERVICE" ||
  fail "WiFi provisioning must pull in NetworkManager online readiness"
grep -q 'saha-bt-wifi-provision-wait' \
  "$BT_WIFI_PROVISION" ||
  fail "saha-bt-wifi-provision must install adapter wait helper"
grep -q 'packagegroup-saha-bluetooth' "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-common.inc" ||
  fail "default Saha images must include bluetooth packagegroup"
grep -q 'bluetooth' "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/distro/tegra-saha.conf" ||
  fail "tegra-saha distro must enable bluetooth DISTRO_FEATURE"

grep -q 'gfortran' "$ROOT_DIR/docker/Dockerfile.yocto-builder" ||
  fail "Yocto builder image must include gfortran"

for removed_ros_path in \
  "$ROOT_DIR/kas/include/ros-jazzy.yml" \
  "$ROOT_DIR/kas/targets/orin-nx-16g-p3768-ros-jazzy.yml" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-ros-jazzy-deps.bb" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-ros-jazzy-deps.bb"; do
  [ ! -e "$removed_ros_path" ] || fail "ROS build path should be removed: $removed_ros_path"
done

if rg -n 'CORE_IMAGE_BASE_INSTALL \+= ".*(cuda-samples|nvidia-container-toolkit|packagegroup-saha-basetests)' \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images" >/tmp/saha-nonbasic-default-packages.out; then
  cat /tmp/saha-nonbasic-default-packages.out >&2
  fail "default base image must avoid samples and container toolkit extras"
fi

if rg -n 'DISTRO_FEATURES_DEFAULT( |"|})|TCLIBCAPPEND|S = "\$\{WORKDIR\}"|file://\$\{MACHINE\}/flashvars' \
  "$ROOT_DIR/saha-layers" >/tmp/saha-obsolete-wrynose-patterns.out; then
  cat /tmp/saha-obsolete-wrynose-patterns.out >&2
  fail "obsolete Wrynose-incompatible layer pattern found"
fi

if rg -n '\$\{WORKDIR\}/skip-dummy-interfaces.conf' \
  "$ROOT_DIR/saha-layers" >/tmp/saha-obsolete-workdir-source-paths.out; then
  cat /tmp/saha-obsolete-workdir-source-paths.out >&2
  fail "Wrynose unpacked source files must be read from UNPACKDIR"
fi

for legacy_path in \
  "$ROOT_DIR/resources" \
  "$ROOT_DIR/scripts/init.sh" \
  "$ROOT_DIR/scripts/clear.sh" \
  "$ROOT_DIR/scripts-setup" \
  "$ROOT_DIR/setup-env" \
  "$ROOT_DIR/dockers" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/.templateconf" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/templates" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/conf/machine" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-kernel" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-bsp/tegra-binaries/tegra-bootfiles_%.bbappend" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-bsp/tegra-binaries/tegra-saha-layout.bb" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-bsp/tegra-binaries/tegra-saha-layout" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/data-overlay-setup" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/environment-setup" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-env.bb" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/packagegroups/packagegroup-saha-basetests.bb" \
  "$ROOT_DIR/saha-layers/meta-tegra-saha/scripts"; do
  [ ! -e "$legacy_path" ] || fail "legacy path should be removed: $legacy_path"
done

if rg -n 'rolling|apollo-nx|xavier-nx|tegra-rolling-kernel|tegra-saha-layout|data-overlay-setup|packagegroup-saha-env|packagegroup-saha-basetests|environment-setup|ros2_arm64|ros-jazzy|saha-image-ros|packagegroup-saha-ros-jazzy' \
  "$ROOT_DIR/kas" "$ROOT_DIR/saha-layers" "$ROOT_DIR/scripts" >/tmp/saha-legacy-references.out; then
  cat /tmp/saha-legacy-references.out >&2
  fail "legacy machine, ROS, or removed recipe reference found"
fi

shell_dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-shell" agx-thor-devkit)"
contains "$shell_dry_run_output" "kas shell kas/targets/agx-thor-devkit.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-jazzy.yml:kas/include/docker-images.yml"
contains "$shell_dry_run_output" " -it "

shell_command_dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-shell" orin-nx-16g-p3768 -c "bitbake package-index")"
contains "$shell_command_dry_run_output" "kas shell kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-jazzy.yml:kas/include/docker-images.yml -c bitbake\\ package-index"
if [[ "$shell_command_dry_run_output" == *" -it "* ]]; then
  fail "non-interactive shell command should not allocate a TTY"
fi

lyrical_shell_command_dry_run_output="$(SAHA_DRY_RUN=1 SAHA_ROS_DISTRO=lyrical "$ROOT_DIR/scripts/saha-shell" orin-nx-16g-p3768 -c "bitbake -p")"
contains "$lyrical_shell_command_dry_run_output" "kas shell kas/targets/orin-nx-16g-p3768.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-lyrical.yml:kas/include/docker-images.yml -c bitbake\\ -p"

validate_dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-validate" agx-orin-devkit)"
contains "$validate_dry_run_output" "kas dump --skip repo_setup_loop --skip finish_setup_repos --skip repos_checkout --skip repos_apply_patches kas/targets/agx-orin-devkit.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-jazzy.yml:kas/include/docker-images.yml"

lyrical_validate_dry_run_output="$(SAHA_DRY_RUN=1 SAHA_ROS_DISTRO=lyrical "$ROOT_DIR/scripts/saha-validate" agx-orin-devkit)"
contains "$lyrical_validate_dry_run_output" "kas dump --skip repo_setup_loop --skip finish_setup_repos --skip repos_checkout --skip repos_apply_patches kas/targets/agx-orin-devkit.yml:kas/include/image-profile-robot.yml:kas/include/ros-distro-lyrical.yml:kas/include/docker-images.yml"

echo "PASS: build framework contract"
