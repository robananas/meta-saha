#!/usr/bin/env python3

from __future__ import annotations

import logging
import os
import sys

from gatt_server import GattProvisioner
from wifi_manager import sync_matter_wifi_credentials


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    local_name = os.environ.get("SAHA_BT_WIFI_LOCAL_NAME", "Roban-Bluetooth")
    adapter_wait = int(os.environ.get("SAHA_BT_WIFI_ADAPTER_WAIT", "45"))
    try:
        if sync_matter_wifi_credentials():
            logging.info("Matter WiFi credentials synchronized from NetworkManager")
        GattProvisioner(local_name=local_name, adapter_wait=adapter_wait).run()
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception("saha-bt-wifi-provision failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
