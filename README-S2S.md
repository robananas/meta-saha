# Optional Roban S2S image integration

Add `kas/include/s2s.yml` to a kas configuration only for an S2S/GPU image. The include installs the NVIDIA container runtime registration, the independent `saha-s2s` Compose project, and the local-only `roban-s2s:arm64` archive preload. Default images and the existing LiveKit Compose project are unchanged.

Before parsing/building `saha-s2s-container-image`, place a Docker archive tagged `roban-s2s:arm64` at `DL_DIR/roban-s2s.tar`. The recipe validates that the archive contains exactly one ARM64 image with that tag and never pulls from a registry. Models are not part of the image or rootfs. Provision benchmark-selected models after flashing under `/var/lib/saha/s2s/models`, record revisions in `/etc/default/saha-s2s`, and create `manifest.sha256` with paths relative to the model root. Startup verifies the manifest when present.

The service listens on configurable TCP port `SAHA_S2S_PORT` (default `8765`). It uses host networking because aiortc ICE host candidates require dynamic UDP sockets; this avoids pretending that a fixed UDP range exists in the Phase 2 backend. `ROBAN_S2S_ICE_SERVERS` accepts the backend's JSON STUN/TURN list. `/health` is liveness and `/ready` is model/runtime readiness. Compose explicitly selects `runtime: nvidia`; NVIDIA is registered but is not Docker's global default.

No fixed rootfs increase is included before the S2S archive exists. Yocto's normal installed-size accounting includes the archive. During Phase 5, measure the archive, generated rootfs, and Docker unpacked size, then add only the observed safety margin to `kas/include/s2s.yml` if the target partition needs one; model sizes are excluded because models are post-flash assets.
