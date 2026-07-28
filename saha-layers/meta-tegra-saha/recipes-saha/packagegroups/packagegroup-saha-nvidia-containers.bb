DESCRIPTION = "Optional NVIDIA GPU container runtime integration"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    nvidia-container-toolkit \
    saha-nvidia-container-runtime \
"
