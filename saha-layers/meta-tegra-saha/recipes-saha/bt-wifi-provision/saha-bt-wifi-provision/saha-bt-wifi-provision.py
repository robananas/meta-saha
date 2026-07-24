#!/usr/bin/env python3

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from gatt_server import GattProvisioner
from wifi_manager import sync_matter_wifi_credentials


def keep_matter_wifi_credentials_synchronized() -> None:
    while True:
        try:
            if sync_matter_wifi_credentials():
                logging.debug("Matter WiFi credentials synchronized from NetworkManager")
        except Exception:
            logging.exception("Unable to synchronize Matter WiFi credentials from NetworkManager")
        time.sleep(5)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    local_name = os.environ.get("SAHA_BT_WIFI_LOCAL_NAME", "Roban-Bluetooth")
    adapter_wait = int(os.environ.get("SAHA_BT_WIFI_ADAPTER_WAIT", "45"))
    try:
        threading.Thread(
            target=keep_matter_wifi_credentials_synchronized,
            name="matter-wifi-credential-sync",
            daemon=True,
        ).start()
        GattProvisioner(local_name=local_name, adapter_wait=adapter_wait).run()
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception("saha-bt-wifi-provision failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
