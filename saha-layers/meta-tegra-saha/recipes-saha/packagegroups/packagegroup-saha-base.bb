DESCRIPTION = "Packagegroup for inclusion in all Saha images"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    haveged \
    procps \
    sshfs-fuse \
    strace \
    tcpdump \
    tshark \
    can-utils \
    kernel-module-gs-usb \
    tegra-tools-tegrastats \
    saha-board-status \
    saha-data-layout \
    dosfstools \
    ripgrep \
    coreutils \
"
