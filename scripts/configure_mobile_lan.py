"""Set the host LAN address for local phone pairing (run again after changing networks)."""

import ipaddress
import socket
import subprocess
import sys
from pathlib import Path


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.connect(("8.8.8.8", 80))
        address = connection.getsockname()[0]
    if sys.platform == "darwin":
        for interface in ("en0", "en1", "en2"):
            result = subprocess.run(["ipconfig", "getifaddr", interface], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                address = result.stdout.strip()
                break
    ip = ipaddress.ip_address(address)
    if not any(ip in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        raise SystemExit("No usable LAN IP found; set BEACON_MOBILE_PUBLIC_URL manually.")
    root = Path(__file__).resolve().parents[1]
    value = f"BEACON_MOBILE_PUBLIC_URL=http://{address}:8000"
    for relative in ("infra/.env", "apps/api/.env"):
        path = root / relative
        rows = path.read_text().splitlines() if path.exists() else []
        rows = [row for row in rows if not row.startswith("BEACON_MOBILE_PUBLIC_URL=")]
        path.write_text("\n".join([*rows, value]) + "\n")
    print(f"Phone pairing address: http://{address}:8000")
    print("Recreate the local API container, then generate a new pairing QR code.")


if __name__ == "__main__":
    main()
