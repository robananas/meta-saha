SUMMARY = "Preloaded workflow control MCP container image"
DESCRIPTION = "Packages a validated local roban-workflow-mcp:arm64 Docker archive for offline first boot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PV = "1.0"
WORKFLOW_MCP_IMAGE ?= "roban-workflow-mcp:arm64"
WORKFLOW_MCP_IMAGE_ARCH ?= "arm64"
WORKFLOW_MCP_LOCAL_TAR ?= "${DL_DIR}/roban-workflow-mcp.tar"

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
    WORKFLOW_MCP_IMAGE="${WORKFLOW_MCP_IMAGE}" \
    WORKFLOW_MCP_IMAGE_ARCH="${WORKFLOW_MCP_IMAGE_ARCH}" \
    WORKFLOW_MCP_LOCAL_TAR="${WORKFLOW_MCP_LOCAL_TAR}" \
    sh ${UNPACKDIR}/fetch-image.sh "${WORKDIR}/roban-workflow-mcp.tar"
}

do_install() {
    install -d ${D}${datadir}/saha/workflow-mcp
    install -m 0644 ${WORKDIR}/roban-workflow-mcp.tar \
        ${D}${datadir}/saha/workflow-mcp/image.tar
}

FILES:${PN} = "${datadir}/saha/workflow-mcp/image.tar"
