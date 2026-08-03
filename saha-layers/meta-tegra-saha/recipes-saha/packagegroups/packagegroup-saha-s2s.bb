DESCRIPTION = "Optional independent Roban S2S runtime and image preload"
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    ollama \
    packagegroup-saha-nvidia-containers \
    saha-s2s \
"
