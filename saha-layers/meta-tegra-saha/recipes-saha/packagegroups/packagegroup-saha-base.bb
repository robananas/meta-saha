DESCRIPTION = "Packagegroup for inclusion in all Saha images"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    haveged \
    procps \
    sshfs-fuse \
    strace \
    can-utils \
    tegra-tools-tegrastats \
    saha-board-status \
    saha-data-layout \
    dosfstools \
    ripgrep \
    coreutils \
"
