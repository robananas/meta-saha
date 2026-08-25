DESCRIPTION = "Docker runtime, compose stack, and preloaded container images"

LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    ca-certificates \
    docker \
    docker-compose \
    iproute2 \
    curl \
    saha-docker-compose \
    saha-homeassistant-config \
    saha-homeassistant-bootstrap \
    saha-homeassistant-mcp \
    saha-workflow-mcp \
    packagegroup-saha-nvidia-containers \
    ollama \
    saha-s2s \
"
