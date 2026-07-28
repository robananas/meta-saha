DESCRIPTION = "Optional independent Roban S2S runtime and image preload"
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    packagegroup-saha-nvidia-containers \
    saha-s2s-container-image \
    saha-s2s \
"
