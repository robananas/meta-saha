SUMMARY = "Preloaded LiveKit Server container image for Jetson (arm64)"
DESCRIPTION = "Installs the official LiveKit Server ARM64 image as a Docker archive for offline first boot."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "1.13.4"

LIVEKIT_SERVER_IMAGE ?= "livekit/livekit-server:v1.13.4"
LIVEKIT_SERVER_IMAGE_OS ?= "linux"
LIVEKIT_SERVER_IMAGE_ARCH ?= "arm64"
LIVEKIT_SERVER_LOCAL_TAR ?= "${DL_DIR}/livekit-server-container.tar"

SRC_URI = "file://fetch-image.sh"
DEPENDS = "ca-certificates-native skopeo-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"

addtask fetch_image after do_unpack before do_patch
do_fetch_image[depends] += "ca-certificates-native:do_populate_sysroot skopeo-native:do_populate_sysroot"
do_fetch_image[network] = "1"
do_fetch_image[prefuncs] = "extend_recipe_sysroot"

do_fetch_image() {
    LIVEKIT_SERVER_IMAGE="${LIVEKIT_SERVER_IMAGE}" \
    LIVEKIT_SERVER_IMAGE_OS="${LIVEKIT_SERVER_IMAGE_OS}" \
    LIVEKIT_SERVER_IMAGE_ARCH="${LIVEKIT_SERVER_IMAGE_ARCH}" \
    LIVEKIT_SERVER_LOCAL_TAR="${LIVEKIT_SERVER_LOCAL_TAR}" \
    DL_DIR="${DL_DIR}" \
    SKOPEO_BIN="${STAGING_SBINDIR_NATIVE}/skopeo" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/livekit-server-container.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/livekit-server
    install -m 0644 ${WORKDIR}/livekit-server-container.tar ${D}${datadir}/saha/livekit-server/image.tar
}

FILES:${PN} = "${datadir}/saha/livekit-server/image.tar"
