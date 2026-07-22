SUMMARY = "Preloaded local Roban LiveKit Agent container image"
DESCRIPTION = "Exports the locally built livekit-agent:arm64 image as a Docker archive for offline first boot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "1.0"

LIVEKIT_AGENT_IMAGE ?= "livekit-agent:arm64"
LIVEKIT_AGENT_IMAGE_ARCH ?= "arm64"
LIVEKIT_AGENT_LOCAL_TAR ?= "${DL_DIR}/livekit-agent.tar"

SRC_URI = "file://fetch-image.sh"
DEPENDS = "ca-certificates-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"

addtask fetch_image after do_unpack before do_patch
do_fetch_image[network] = "1"

do_fetch_image() {
    LIVEKIT_AGENT_IMAGE="${LIVEKIT_AGENT_IMAGE}" \
    LIVEKIT_AGENT_IMAGE_ARCH="${LIVEKIT_AGENT_IMAGE_ARCH}" \
    LIVEKIT_AGENT_LOCAL_TAR="${LIVEKIT_AGENT_LOCAL_TAR}" \
    DL_DIR="${DL_DIR}" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/livekit-agent.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/livekit-agent
    install -m 0644 ${WORKDIR}/livekit-agent.tar ${D}${datadir}/saha/livekit-agent/image.tar
}

FILES:${PN} = "${datadir}/saha/livekit-agent/image.tar"
