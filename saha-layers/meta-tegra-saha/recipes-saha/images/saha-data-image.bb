SUMMARY = "Initial Saha DATA partition filesystem"
LICENSE = "MIT"

inherit core-image

IMAGE_FEATURES = ""
IMAGE_FSTYPES = "ext4"
IMAGE_ROOTFS_SIZE = "12582912"
IMAGE_ROOTFS_EXTRA_SPACE = "262144"
IMAGE_LINGUAS = ""
IMAGE_INSTALL = "packagegroup-saha-container-preloads"

saha_prepare_data_image() {
    install -d -m 0755 ${IMAGE_ROOTFS}/preload
    for name in homeassistant matter-server roban-workflow-api livekit-server livekit-agent s2s; do
        src="${IMAGE_ROOTFS}${datadir}/saha/$name/image.tar"
        dst="${IMAGE_ROOTFS}/preload/$name"
        test -s "$src" || bbfatal "DATA preload archive missing: $name"
        install -d -m 0755 "$dst"
        mv "$src" "$dst/image.tar"
        (cd "$dst" && sha256sum image.tar > manifest.sha256)
    done
    rm -rf ${IMAGE_ROOTFS}${datadir}/saha
    install -d -m 0700 ${IMAGE_ROOTFS}/docker ${IMAGE_ROOTFS}/models/s2s ${IMAGE_ROOTFS}/model-cache/s2s
    install -d -m 0755 ${IMAGE_ROOTFS}/log/journal ${IMAGE_ROOTFS}/log/ros ${IMAGE_ROOTFS}/log/app
    printf '1\n' > ${IMAGE_ROOTFS}/.saha-data-layout-version
    (cd ${IMAGE_ROOTFS} && find preload -type f -print0 | sort -z | xargs -0 sha256sum > preload/SHA256SUMS)
    printf '{"layoutVersion":1,"preloads":"SHA256SUMS"}\n' > ${IMAGE_ROOTFS}/preload/manifest.json
}
ROOTFS_POSTPROCESS_COMMAND += "saha_prepare_data_image;"

inherit nopackages
