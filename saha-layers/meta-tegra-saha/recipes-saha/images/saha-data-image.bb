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
    for name in homeassistant homeassistant-mcp matter-server roban-workflow-api livekit-server livekit-agent s2s; do
        src="${IMAGE_ROOTFS}${datadir}/saha/$name/image.tar"
        dst="${IMAGE_ROOTFS}/preload/$name"
        test -s "$src" || bbfatal "DATA preload archive missing: $name"
        install -d -m 0755 "$dst"
        mv "$src" "$dst/image.tar"
        (cd "$dst" && sha256sum image.tar > manifest.sha256)
    done
    rm -rf ${IMAGE_ROOTFS}${datadir}/saha
    install -d -m 0700 ${IMAGE_ROOTFS}/docker
    test -s ${IMAGE_ROOTFS}/models/s2s/manifest.sha256 || bbfatal "base KWS/VAD manifest missing from DATA image"
    (cd ${IMAGE_ROOTFS}/models/s2s && sha256sum -c manifest.sha256) || bbfatal "base KWS/VAD verification failed"
    test ! -e ${IMAGE_ROOTFS}/models/s2s/stt || bbfatal "factory DATA image must not contain a default STT model"
    test ! -e ${IMAGE_ROOTFS}/models/s2s/llm || bbfatal "factory DATA image must not contain a default LLM model"
    test ! -e ${IMAGE_ROOTFS}/models/s2s/tts || bbfatal "factory DATA image must not contain a default TTS model"
    test ! -e ${IMAGE_ROOTFS}/model-config/s2s/selection.json || bbfatal "factory DATA image must not contain a default model selection"
    test ! -e ${IMAGE_ROOTFS}/model-config/s2s/pipeline-mode.json || bbfatal "factory DATA image must not contain a default pipeline mode"
    test ! -e ${IMAGE_ROOTFS}/model-secrets/s2s/sub2api.token || bbfatal "factory DATA image must not contain a Grok token"
    chown -R 10002:999 ${IMAGE_ROOTFS}/models/s2s
    find ${IMAGE_ROOTFS}/models/s2s -type d -exec chmod 0750 {} +
    find ${IMAGE_ROOTFS}/models/s2s -type f -exec chmod 0640 {} +
    install -d -o 10002 -g 999 -m 0750 ${IMAGE_ROOTFS}/models/s2s/stt ${IMAGE_ROOTFS}/models/s2s/llm ${IMAGE_ROOTFS}/models/s2s/tts
    install -d -o 10002 -g 999 -m 0750 ${IMAGE_ROOTFS}/model-cache/s2s ${IMAGE_ROOTFS}/tools
    install -d ${IMAGE_ROOTFS}/voiceprints ${IMAGE_ROOTFS}/voiceprints/s2s
    chown 10002:999 ${IMAGE_ROOTFS}/voiceprints ${IMAGE_ROOTFS}/voiceprints/s2s
    chmod 0700 ${IMAGE_ROOTFS}/voiceprints ${IMAGE_ROOTFS}/voiceprints/s2s
    install -d -o 10003 -g 998 -m 0750 ${IMAGE_ROOTFS}/model-cache/s2s/cosyvoice3
    install -d -o 0 -g 0 -m 0750 ${IMAGE_ROOTFS}/model-cache/s2s-model-manager
    install -d -o 0 -g 999 -m 2750 ${IMAGE_ROOTFS}/model-config/s2s ${IMAGE_ROOTFS}/model-config/s2s/voices
    install -d -o 0 -g 999 -m 0750 ${IMAGE_ROOTFS}/model-secrets ${IMAGE_ROOTFS}/model-secrets/s2s
    install -d -m 0755 ${IMAGE_ROOTFS}/log/journal ${IMAGE_ROOTFS}/log/ros ${IMAGE_ROOTFS}/log/app
    printf '1\n' > ${IMAGE_ROOTFS}/.saha-data-layout-version
    (cd ${IMAGE_ROOTFS} && find preload -type f -print0 | sort -z | xargs -0 sha256sum > preload/SHA256SUMS)
    printf '{"layoutVersion":1,"preloads":"SHA256SUMS"}\n' > ${IMAGE_ROOTFS}/preload/manifest.json
}
ROOTFS_POSTPROCESS_COMMAND += "saha_prepare_data_image;"

inherit nopackages
