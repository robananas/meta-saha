SUMMARY = "Preloaded Home Assistant MCP container image"
DESCRIPTION = "Packages a validated local roban-ha-mcp:arm64 Docker archive for offline first boot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "1.0"
MCP_IMAGE ?= "roban-ha-mcp:arm64"
MCP_IMAGE_ARCH ?= "arm64"
MCP_LOCAL_TAR ?= "${DL_DIR}/roban-ha-mcp.tar"

SRC_URI = "file://fetch-image.sh"
DEPENDS = "ca-certificates-native"
PACKAGE_ARCH = "${MACHINE_ARCH}"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP:${PN} += "already-stripped ldflags dev-so"

addtask fetch_image after do_unpack before do_patch
do_fetch_image[network] = "0"
do_fetch_image[nostamp] = "1"

do_fetch_image() {
    MCP_IMAGE="${MCP_IMAGE}" \
    MCP_IMAGE_ARCH="${MCP_IMAGE_ARCH}" \
    MCP_LOCAL_TAR="${MCP_LOCAL_TAR}" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/roban-ha-mcp.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/homeassistant-mcp
    install -m 0644 ${WORKDIR}/roban-ha-mcp.tar \
        ${D}${datadir}/saha/homeassistant-mcp/image.tar
}

FILES:${PN} = "${datadir}/saha/homeassistant-mcp/image.tar"
