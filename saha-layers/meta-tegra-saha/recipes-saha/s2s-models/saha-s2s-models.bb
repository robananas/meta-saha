SUMMARY = "Pinned production speech models for Roban S2S"
DESCRIPTION = "Seeds the factory-reset DATA image with the exact offline KWS, VAD, STT, and TTS assets used by the Roban production pipeline."
LICENSE = "CLOSED"

PV = "1.0"
PACKAGE_ARCH = "all"
INHIBIT_DEFAULT_DEPS = "1"

S2S_MODELS_DL_DIR ?= "${DL_DIR}/saha-s2s-models"
S2S_KWS_ARCHIVE = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2"
S2S_KWS_SHA256 = "b2f7c89690dc8ce4c6ed6afeab7cd800c36ad1421fb6b6302b4a4b194cf7f35f"
S2S_VAD_FILE = "silero_vad.onnx"
S2S_VAD_SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
S2S_STT_ARCHIVE = "sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2"
S2S_STT_SHA256 = "da92b3db5218c5be53aad53e57d1b6e63e7fc98a0e054fbdd6dbe18e9c6b1450"
S2S_TTS_ARCHIVE = "sherpa-onnx-vits-zh-ll.tar.bz2"
S2S_TTS_SHA256 = "f7393d1bbc59709d5f52ea76cd5bceeec62f6a29f9c1f79ff64b4c15ec841f3a"

SRC_URI = "file://prepare-models.sh file://revisions.txt file://LICENSE.models"

addtask prepare_models after do_unpack before do_patch
do_prepare_models[network] = "0"
do_prepare_models[nostamp] = "1"

do_prepare_models() {
    S2S_MODELS_DL_DIR="${S2S_MODELS_DL_DIR}" \
    S2S_KWS_ARCHIVE="${S2S_KWS_ARCHIVE}" S2S_KWS_SHA256="${S2S_KWS_SHA256}" \
    S2S_VAD_FILE="${S2S_VAD_FILE}" S2S_VAD_SHA256="${S2S_VAD_SHA256}" \
    S2S_STT_ARCHIVE="${S2S_STT_ARCHIVE}" S2S_STT_SHA256="${S2S_STT_SHA256}" \
    S2S_TTS_ARCHIVE="${S2S_TTS_ARCHIVE}" S2S_TTS_SHA256="${S2S_TTS_SHA256}" \
    sh ${UNPACKDIR}/prepare-models.sh ${WORKDIR}/models
}

do_install() {
    install -d -o 10002 -g 999 -m 0750 ${D}/models/s2s
    cp -R --no-preserve=ownership ${WORKDIR}/models/. ${D}/models/s2s/
    install -m 0640 ${UNPACKDIR}/revisions.txt ${D}/models/s2s/revisions.txt
    install -m 0640 ${UNPACKDIR}/LICENSE.models ${D}/models/s2s/LICENSE.models
    chown -R 10002:999 ${D}/models/s2s
    find ${D}/models/s2s -type d -exec chmod 0750 {} +
    find ${D}/models/s2s -type f -exec chmod 0640 {} +
    (cd ${D}/models/s2s && find . -type f ! -name manifest.sha256 | LC_ALL=C sort | while IFS= read -r file; do sha256sum "$file"; done > manifest.sha256)
    chown 10002:999 ${D}/models/s2s/manifest.sha256
    chmod 0640 ${D}/models/s2s/manifest.sha256
}

FILES:${PN} = "/models/s2s"
INSANE_SKIP:${PN} += "arch already-stripped"
