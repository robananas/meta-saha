# meta-saha

`meta-saha` is a Yocto Project distro layer and build framework for NVIDIA Jetson systems. The primary workflow builds Jetson Orin and Thor images with kas inside Docker, so the host only needs Docker and does not need kas, bitbake, vcstool, or Yocto build packages installed.

The current baseline is Yocto Project 6.0 Wrynose and OE4T `meta-tegra` Wrynose, targeting JetPack 7.2 / L4T R39.2.0.

## Supported targets

| Target alias | OE4T `MACHINE` | Hardware |
| --- | --- | --- |
| `orin-nx-16g-p3768` | `p3768-0000-p3767-0000` | Jetson Orin NX 16GB module in P3768 carrier |
| `agx-thor-devkit` | `jetson-agx-thor-devkit` | Jetson AGX Thor devkit |
| `agx-orin-devkit` | `jetson-agx-orin-devkit` | Jetson AGX Orin devkit |

List targets with:

```bash
./scripts/saha-targets
```

## Prerequisites

- Docker with permission to run containers as your user.
- Enough disk space for a Yocto build. A first build can consume hundreds of GB across build output, downloads, and sstate cache.
- Network access to fetch Yocto, OpenEmbedded, OE4T, and NVIDIA sources.

No host-side Yocto package setup is part of the primary build path.

## Build

From the `meta-saha` repository root:

```bash
./scripts/saha-build orin-nx-16g-p3768
```

Build the other priority targets with:

```bash
./scripts/saha-build agx-thor-devkit
./scripts/saha-build agx-orin-devkit
```

The script builds the Docker builder image, mounts persistent cache directories, then runs:

```bash
kas build kas/targets/<target>.yml:kas/include/ros-distro-jazzy.yml
```

`jazzy` is the default ROS 2 distro. Build the same `saha-image-robot` image with ROS 2 Lyrical by setting `SAHA_ROS_DISTRO`:

```bash
SAHA_ROS_DISTRO=lyrical ./scripts/saha-build orin-nx-16g-p3768
```

## Output and caches

Default host paths:

| Path | Purpose |
| --- | --- |
| `build/<target>/` | Default target-specific kas/bitbake build directory for `SAHA_ROS_DISTRO=jazzy` |
| `build/<target>-ros-<distro>/` | Target-specific kas/bitbake build directory for non-default ROS distros such as `lyrical` |
| `downloads/` | Shared Yocto download cache |
| `sstate-cache/` | Shared Yocto sstate cache |

Images are emitted under:

```text
build/<target>/tmp/deploy/images/<machine>/
```

RPM packages are emitted under:

```text
build/<target>/tmp/deploy/rpm/
```

Generate RPM feed metadata after a build with:

```bash
./scripts/saha-shell orin-nx-16g-p3768 -c "bitbake package-index"
```

For `orin-nx-16g-p3768`, the current tegraflash archive is emitted at:

```text
build/orin-nx-16g-p3768/tmp/deploy/images/p3768-0000-p3767-0000/saha-image-robot-p3768-0000-p3767-0000.rootfs.tegraflash-tar.zst
```

For non-default ROS distros, use the distro-specific build directory. For example, `SAHA_ROS_DISTRO=lyrical` emits the Orin NX archive under:

```text
build/orin-nx-16g-p3768-ros-lyrical/tmp/deploy/images/p3768-0000-p3767-0000/saha-image-robot-p3768-0000-p3767-0000.rootfs.tegraflash-tar.zst
```

## Flash and first boot access

Unpack the `.tegraflash-tar.zst` archive on an x86-64 Linux host, put the Jetson in recovery mode with the USB OTG port connected, then run `initrd-flash`:

```bash
mkdir -p ~/scratch/saha-flash
cd ~/scratch/saha-flash
tar xf /path/to/saha-image-robot-p3768-0000-p3767-0000.rootfs.tegraflash-tar.zst
lsusb -d 0955:
./initrd-flash
```

After first boot, the hostname is `soybean`. The image includes `l4t-usb-device-mode`, which creates the target-side USB network endpoint at `192.168.55.1` and serves the host side by DHCP. For bring-up, root login is enabled with an empty password:

```bash
ssh root@192.168.55.1
```

If USB networking is not enumerated by the host, use the serial console instead, for example:

```bash
minicom -D /dev/ttyUSB0
```

Change the empty root password before using the image outside bring-up.

### WiFi on the device

Saha images include NetworkManager with `nmcli` for WiFi setup. USB gadget networking (`l4tbr0`, `192.168.55.1`) stays on systemd-networkd; NetworkManager manages WiFi only.

```bash
nmcli dev wifi list
nmcli dev wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
nmcli dev status
ip addr show wlan0
```

If the WiFi interface name is not `wlan0`, use the name shown by `nmcli dev status`.

Override cache/build locations with environment variables:

```bash
SAHA_BUILD_DIR=/data/yocto/build-orin \
SAHA_DOWNLOADS_DIR=/data/yocto/downloads \
SAHA_SSTATE_DIR=/data/yocto/sstate-cache \
./scripts/saha-build orin-nx-16g-p3768
```

Override the Docker image tag with:

```bash
SAHA_BUILDER_IMAGE=my-saha-builder:wrynose ./scripts/saha-build orin-nx-16g-p3768
```

## Network proxies

`saha-build`, `saha-shell`, and `saha-validate` pass standard proxy variables into both Docker image builds and Docker containers:

```text
HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
http_proxy https_proxy all_proxy no_proxy
```

If none of those variables are present in the current environment, the scripts try to read them from a login interactive `zsh` session. This supports setups where proxy exports live in `~/.zshrc`. Disable this fallback with:

```bash
SAHA_LOAD_ZSHRC_PROXY=0 ./scripts/saha-build orin-nx-16g-p3768
```

If the container can reach upstream sources directly but the host proxy is unstable under Yocto fetch load, force a proxy-free container environment:

```bash
SAHA_NO_PROXY=1 ./scripts/saha-build orin-nx-16g-p3768
```

Dry-run output shows only proxy variable names, not proxy values:

```bash
SAHA_DRY_RUN=1 ./scripts/saha-build orin-nx-16g-p3768
```

## Build tuning

The wrapper defaults to conservative Yocto parallelism to avoid overloading local proxies and developer workstations:

```text
SAHA_BB_NUMBER_THREADS=4
SAHA_BB_NUMBER_PARSE_THREADS=4
SAHA_PARALLEL_MAKE="-j 4"
```

Override these when the network and machine can support more concurrency:

```bash
SAHA_NO_PROXY=1 \
SAHA_BB_NUMBER_THREADS=8 \
SAHA_BB_NUMBER_PARSE_THREADS=8 \
SAHA_PARALLEL_MAKE="-j 8" \
./scripts/saha-build orin-nx-16g-p3768
```

## Interactive shell

Open a Dockerized kas shell for a target:

```bash
./scripts/saha-shell orin-nx-16g-p3768
```

This uses the same mounts and builder image as `saha-build`.

## Validate configuration

Validate a target kas configuration without fetching repositories or starting a build:

```bash
./scripts/saha-validate orin-nx-16g-p3768
```

This is a fast schema/include/config expansion check. A full `saha-build` still depends on network checkout and bitbake.

## Docker application stack

By default, `saha-image-robot` includes Docker, `docker compose`, and preloaded container images for Home Assistant, Matter Server, and `roban-workflow-api:arm64`. Disable the stack at build time with:

```bash
HAVE_DOCKER_IMAGE=0 ./scripts/saha-build orin-nx-16g-p3768
```

This omits `docker`, `docker-compose`, the compose launcher, preloaded tarballs, and the extra rootfs space reserved for them. ROS 2, USB gadget networking, and WiFi support are unaffected.

On the device, `saha-docker-compose.service` loads the prebuilt images and starts the stack from `/opt/roban/compose/compose.yaml`. Data paths use `/var/lib/homeassistant` and `/var/lib/matter-server`. To change the stack, edit `saha-layers/meta-tegra-saha/recipes-saha/docker-compose/saha-docker-compose/compose.yaml` and rebuild.

### Build-time image caches

| Image | Default host cache path |
| --- | --- |
| Home Assistant | `downloads/homeassistant-container.tar` |
| Matter Server | `downloads/matter-server-container.tar` |
| Roban workflow API | `downloads/roban-workflow-api.tar` |

Preload images on the build host:

```bash
docker pull --platform linux/arm64 ghcr.io/home-assistant/home-assistant:stable
docker save ghcr.io/home-assistant/home-assistant:stable -o downloads/homeassistant-container.tar

docker pull --platform linux/arm64 ghcr.io/matter-js/python-matter-server:stable
docker tag ghcr.io/matter-js/python-matter-server:stable ghcr.io/matter-js/python-matter-server:arm64
docker save ghcr.io/matter-js/python-matter-server:arm64 -o downloads/matter-server-container.tar

docker save roban-workflow-api:arm64 -o downloads/roban-workflow-api.tar

./scripts/saha-build orin-nx-16g-p3768
```

Home Assistant and Matter Server can also be fetched from their registries during the Yocto build when no local cache is available. `roban-workflow-api:arm64` must be present locally or in `downloads/roban-workflow-api.tar`.

Defaults live in `/etc/default/saha-docker-compose`:

| Variable | Default |
| --- | --- |
| `SAHA_DOCKER_COMPOSE_DIR` | `/opt/roban/compose` |
| `SAHA_DOCKER_COMPOSE_FILE` | `/opt/roban/compose/compose.yaml` |
| `SAHA_DOCKER_COMPOSE_TZ` | `Asia/Shanghai` |
| `SAHA_DOCKER_COMPOSE_PULL` | `0` |
| `SAHA_HOMEASSISTANT_IMAGE` | `ghcr.io/home-assistant/home-assistant:stable` |
| `SAHA_MATTER_SERVER_IMAGE` | `ghcr.io/matter-js/python-matter-server:arm64` |
| `SAHA_ROBAN_WORKFLOW_IMAGE` | `roban-workflow-api:arm64` |

Check service status on the device:

```bash
systemctl status saha-docker-compose docker
docker compose -f /opt/roban/compose/compose.yaml ps
docker images
```

Home Assistant is available at `http://<device-ip>:8123` once the stack is running.

## ROS 2

`saha-image-robot` includes ROS 2 by default through `ros-base` and `ros2cli-common-extensions`. There is no separate ROS image target; build and flash `saha-image-robot` for the robot rootfs.

Supported ROS 2 distros:

| `SAHA_ROS_DISTRO` | kas include |
| --- | --- |
| `jazzy` | `kas/include/ros-distro-jazzy.yml` |
| `lyrical` | `kas/include/ros-distro-lyrical.yml` |

| `HAVE_DOCKER_IMAGE` | Effect |
| --- | --- |
| `1` (default) | Include Docker, docker compose stack, and preloaded container images |
| `0` | Omit Docker, compose launcher, and preloaded images |

After flashing, initialize the ROS environment with:

```bash
source /opt/ros/<distro>/setup.sh
ros2 --help
```

## Image scope

The supported image target is `saha-image-robot`. It is layered on the reusable `saha-image-base` recipe and includes the Jetson BSP base, CUDA runtime libraries, OpenSSH bring-up access, USB device-mode networking support, NetworkManager with `nmcli` for WiFi, the configured ROS 2 runtime and CLI tools, and by default Docker with a compose-managed application stack (Home Assistant, Matter Server, and Roban workflow API).

The image does not include CUDA samples or Jetson GPU container runtime tooling. Add `nvidia-container-toolkit` later through an optional image or kas include if GPU-backed containers are required; OE4T R39.2 removed the old `nvidia-docker` recipe.

## Add a target

1. Confirm the machine exists in OE4T `meta-tegra` Wrynose.
2. Add an alias to `scripts/saha-lib`.
3. Add `kas/targets/<alias>.yml` with the matching `machine`.
4. Run:

```bash
bash tests/test-build-framework.sh
./scripts/saha-validate <alias>
```

## Removed legacy flow

The old `resources/*.repos`, `scripts/init.sh`, `setup-env`, `scripts-setup/`, local machine templates, and Xavier NX / `rolling-nx` support have been removed. The supported path is Docker plus kas through `scripts/saha-build`.

## License

This project is open sourced under Apache 2.0 License.

The source code originally forked from OE4T `tegra-demo-distro` is under the MIT License; see `docs/licenses/OE4T.license`.
