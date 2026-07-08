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

## Home Assistant container

`saha-image-robot` includes Docker and the official Home Assistant container launcher by default. A `homeassistant-container.service` systemd unit runs `ghcr.io/home-assistant/home-assistant:stable` with host networking. The service is enabled on boot and starts after `docker.service`.

Defaults live in `/etc/default/homeassistant-container`:

| Variable | Default |
| --- | --- |
| `SAHA_HOMEASSISTANT_CONFIG_DIR` | `/var/lib/homeassistant` |
| `SAHA_HOMEASSISTANT_IMAGE` | `ghcr.io/home-assistant/home-assistant:stable` |
| `SAHA_HOMEASSISTANT_CONTAINER_NAME` | `homeassistant` |
| `SAHA_HOMEASSISTANT_TIMEZONE` | `UTC` |
| `SAHA_HOMEASSISTANT_PULL` | `1` |

After flashing and first boot, Home Assistant pulls its container image on first start. This needs network access. Then open:

```text
http://<device-ip>:8123
```

Check service status on the device:

```bash
systemctl status homeassistant-container
systemctl status docker
docker ps
```

## ROS 2

`saha-image-robot` includes ROS 2 by default through `ros-base` and `ros2cli-common-extensions`. There is no separate ROS image target; build and flash `saha-image-robot` for the robot rootfs.

Supported ROS 2 distros:

| `SAHA_ROS_DISTRO` | kas include |
| --- | --- |
| `jazzy` | `kas/include/ros-distro-jazzy.yml` |
| `lyrical` | `kas/include/ros-distro-lyrical.yml` |

After flashing, initialize the ROS environment with:

```bash
source /opt/ros/<distro>/setup.sh
ros2 --help
```

## Image scope

The supported image target is `saha-image-robot`. It is layered on the reusable `saha-image-base` recipe and includes the Jetson BSP base, CUDA runtime libraries, OpenSSH bring-up access, USB device-mode networking support, Docker with the official Home Assistant container launcher, and the configured ROS 2 runtime and CLI tools.

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
