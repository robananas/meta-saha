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
kas build kas/targets/<target>.yml
```

## Output and caches

Default host paths:

| Path | Purpose |
| --- | --- |
| `build/<target>/` | Target-specific kas/bitbake build directory |
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

## Image scope

The default `saha-image-robot` image is intentionally a basic Jetson BSP image layered on the reusable `saha-image-base` recipe.

The default MVP image does not include CUDA samples or Jetson container runtime tooling. Add `nvidia-container-toolkit` later through an optional image or kas include if container runtime support is required; OE4T R39.2 removed the old `nvidia-docker` recipe.

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
