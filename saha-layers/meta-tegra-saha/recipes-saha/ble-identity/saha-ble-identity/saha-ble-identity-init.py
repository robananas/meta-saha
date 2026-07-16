#!/usr/bin/env python3
"""Create, persist, and apply the Saha BLE Static Random Identity Address."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ADDRESS_DIR = Path("/var/lib/saha/ble-identity")
ADDRESS_FILE = ADDRESS_DIR / "address"
HCI_DEVICE = Path("/sys/class/bluetooth/hci0")
BTMGMT = "/usr/bin/btmgmt"
ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


def validate_address(value: str) -> str:
    address = value.strip().upper()
    if not ADDRESS_RE.fullmatch(address):
        raise ValueError("identity address must use XX:XX:XX:XX:XX:XX format")

    octets = bytes.fromhex(address.replace(":", ""))
    if octets[0] & 0xC0 != 0xC0:
        raise ValueError("identity address is not a static random address")

    random_part = int.from_bytes(octets, "big") & ((1 << 46) - 1)
    if random_part in (0, (1 << 46) - 1):
        raise ValueError("identity address has a reserved random portion")
    return address


def generate_address() -> str:
    while True:
        octets = bytearray(os.urandom(6))
        octets[0] = (octets[0] & 0x3F) | 0xC0
        address = ":".join(f"{octet:02X}" for octet in octets)
        try:
            return validate_address(address)
        except ValueError:
            continue


def persist_address(address: str) -> None:
    ADDRESS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ADDRESS_DIR, 0o700)
    temporary = ADDRESS_DIR / f".address.tmp.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(address + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, ADDRESS_FILE)
            os.chmod(ADDRESS_FILE, 0o600)
            directory_fd = os.open(ADDRESS_DIR, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def load_address() -> str | None:
    if not ADDRESS_FILE.exists():
        return None
    address = validate_address(ADDRESS_FILE.read_text(encoding="ascii"))
    os.chmod(ADDRESS_FILE, 0o600)
    return address


def wait_for_controller(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not HCI_DEVICE.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("hci0 did not appear after tegra-bluetooth.service")
        time.sleep(0.25)


def run_btmgmt(*arguments: str) -> None:
    command = [BTMGMT, "--index", "0", *arguments]
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL)


def main() -> int:
    try:
        wait_for_controller()
        stored_address = load_address()
        address = stored_address or generate_address()
        run_btmgmt("power", "off")
        run_btmgmt("le", "on")
        run_btmgmt("bredr", "off")
        run_btmgmt("static-addr", address)
        if stored_address is None:
            persist_address(address)
            print(f"generated BLE identity {address}")
        else:
            print(f"restored BLE identity {address}")
    except (OSError, ValueError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"saha-ble-identity-init: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
