#!/usr/bin/env python3
"""Run python-matter-server without any public network dependencies."""

from __future__ import annotations

import logging
from typing import Any


async def _skip_certificate_fetch(*args: Any, **kwargs: Any) -> int:
    logging.getLogger("matter_server.server.helpers.paa_certificates").info(
        "Offline mode: using bundled PAA certificates"
    )
    return 0


async def _skip_vendor_fetch(self: Any) -> None:
    logging.getLogger("matter_server.server.vendor_info").info(
        "Offline mode: using cached vendor information"
    )


async def _skip_dcl_ota(*args: Any, **kwargs: Any) -> tuple[None, None]:
    logging.getLogger("matter_server.server.ota.dcl").info(
        "Offline mode: DCL OTA lookup disabled"
    )
    return None, None


async def _reject_external_ota(self: Any, update_desc: dict[str, Any]) -> None:
    raise RuntimeError("External OTA downloads are disabled in offline mode")


def main() -> None:
    import matter_server.server.device_controller as device_controller
    import matter_server.server.helpers.paa_certificates as paa_certificates
    import matter_server.server.ota as ota
    import matter_server.server.ota.dcl as ota_dcl
    import matter_server.server.ota.provider as ota_provider
    import matter_server.server.server as server_module
    import matter_server.server.vendor_info as vendor_info

    paa_certificates.fetch_certificates = _skip_certificate_fetch
    server_module.fetch_certificates = _skip_certificate_fetch
    vendor_info.VendorInfo._fetch_vendors = _skip_vendor_fetch
    ota_dcl.check_for_update = _skip_dcl_ota
    ota.check_for_update = _skip_dcl_ota
    device_controller.check_for_update = _skip_dcl_ota
    for value in vars(ota_provider).values():
        if isinstance(value, type) and hasattr(value, "fetch_update"):
            value.fetch_update = _reject_external_ota

    from matter_server.server.__main__ import main as matter_server_main

    matter_server_main()


if __name__ == "__main__":
    main()
