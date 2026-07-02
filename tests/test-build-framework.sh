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
contains "$dry_run_output" "kas build kas/targets/orin-nx-16g-p3768.yml"
contains "$dry_run_output" "/work/build/orin-nx-16g-p3768"
contains "$dry_run_output" "KAS_WORK_DIR=/work/build/orin-nx-16g-p3768"
contains "$dry_run_output" "GIT_HTTP_VERSION=HTTP/1.1"
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

for ignored in ".docker-cache" "build" "downloads" "sstate-cache" "repos"; do
  grep -qxF "$ignored" "$ROOT_DIR/.dockerignore" || fail ".dockerignore missing $ignored"
done

grep -A4 '^  bitbake:' "$ROOT_DIR/kas/include/repos-wrynose.yml" |
  grep -qxF '    branch: "2.18"' ||
  fail "bitbake must use the Wrynose-compatible 2.18 branch"

grep -A3 '^  meta-saha:' "$ROOT_DIR/kas/include/repos-wrynose.yml" |
  grep -qxF '    path: /work/meta-saha' ||
  fail "local meta-saha repo path must match the Docker mount point"

grep -q 'EXTRA_IMAGE_FEATURES ?= "empty-root-password allow-root-login"' "$ROOT_DIR/kas/include/base.yml" ||
  fail "Wrynose image features must not use removed debug-tweaks alias"

grep -q 'BB_HASHSERVE_DB_DIR ?= "${SSTATE_DIR}"' "$ROOT_DIR/kas/include/base.yml" ||
  fail "shared sstate builds should also share hash equivalence database"

grep -q 'PREFERRED_PROVIDER_edk2-nvidia-standalone-mm = "edk2-nvidia-standalone-mm-prebuilt"' "$ROOT_DIR/kas/include/base.yml" ||
  fail "default BSP build should use OE4T prebuilt standalone-mm provider"

grep -A2 '^target:$' "$ROOT_DIR/kas/include/base.yml" |
  grep -qxF '  - saha-image-robot' ||
  fail "default kas build target must be saha-image-robot"

grep -q 'Build saha-image-robot' "$ROOT_DIR/scripts/saha-build" ||
  fail "saha-build help must describe the robot image target"

[ -f "$ROOT_DIR/saha-layers/meta-tegra-saha/recipes-saha/images/saha-image-robot.bb" ] ||
  fail "saha-image-robot recipe must exist"

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

if rg -n 'rolling|apollo-nx|xavier-nx|tegra-rolling-kernel|tegra-saha-layout|data-overlay-setup|packagegroup-saha-env|packagegroup-saha-basetests|environment-setup|ros2_arm64|meta-ros|ros-jazzy|saha-image-ros|packagegroup-saha-ros' \
  "$ROOT_DIR/kas" "$ROOT_DIR/saha-layers" "$ROOT_DIR/scripts" >/tmp/saha-legacy-references.out; then
  cat /tmp/saha-legacy-references.out >&2
  fail "legacy machine, ROS, or removed recipe reference found"
fi

if rg -n 'meta-ros|ros-jazzy|saha-image-ros-jazzy-deps' \
  "$ROOT_DIR/kas/include/base.yml" "$ROOT_DIR/kas/include/repos-wrynose.yml" \
  "$ROOT_DIR/kas/targets/orin-nx-16g-p3768.yml" "$ROOT_DIR/kas/targets/agx-thor-devkit.yml" "$ROOT_DIR/kas/targets/agx-orin-devkit.yml" \
  >/tmp/saha-default-ros-references.out; then
  cat /tmp/saha-default-ros-references.out >&2
  fail "default kas graph must remain ROS-free"
fi

shell_dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-shell" agx-thor-devkit)"
contains "$shell_dry_run_output" "kas shell kas/targets/agx-thor-devkit.yml"
contains "$shell_dry_run_output" " -it "

shell_command_dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-shell" orin-nx-16g-p3768 -c "bitbake package-index")"
contains "$shell_command_dry_run_output" "kas shell kas/targets/orin-nx-16g-p3768.yml -c bitbake\\ package-index"
if [[ "$shell_command_dry_run_output" == *" -it "* ]]; then
  fail "non-interactive shell command should not allocate a TTY"
fi

validate_dry_run_output="$(SAHA_DRY_RUN=1 "$ROOT_DIR/scripts/saha-validate" agx-orin-devkit)"
contains "$validate_dry_run_output" "kas dump --skip repo_setup_loop --skip finish_setup_repos --skip repos_checkout --skip repos_apply_patches kas/targets/agx-orin-devkit.yml"

echo "PASS: build framework contract"
