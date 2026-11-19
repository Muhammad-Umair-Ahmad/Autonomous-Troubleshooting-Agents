import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "labs" / "base"
OUTPUT = ROOT / "results" / "part1"
DEVICES = ("pc1", "r1", "r2", "pc2")


def inspect(device, command):
    if device not in DEVICES:
        raise ValueError(f"Unknown device: {device}")
    result = subprocess.run(
        ["kathara", "exec", "-d", str(LAB), "--wait", device, command],
        capture_output=True,
        text=True,
        timeout=45,
    )
    return {
        "device": device,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def ping_passed(record):
    text = record["stdout"] + record["stderr"]
    match = re.search(r"(\d+(?:\.\d+)?)%\s+packet loss", text)
    return (
        record["returncode"] == 0
        and match is not None
        and float(match.group(1)) == 0
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    observations = []
    for device in DEVICES:
        for command in ("ip -brief address", "ip route show"):
            record = inspect(device, command)
            observations.append(record)
            if record["returncode"] != 0:
                raise RuntimeError(
                    f"Inspection failed on {device}:\n"
                    f"{record['stdout']}\n{record['stderr']}"
                )
    connectivity = [
        inspect("pc1", "ping -c 3 -W 2 10.0.2.10"),
        inspect("pc2", "ping -c 3 -W 2 10.0.1.10"),
    ]
    healthy = all(ping_passed(record) for record in connectivity)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "lab": str(LAB),
        "healthy": healthy,
        "observations": observations,
        "connectivity": connectivity,
    }
    destination = OUTPUT / "network_check.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved network evidence: {destination}")
    if not healthy:
        for record in connectivity:
            print(record["stdout"])
            print(record["stderr"])
        raise SystemExit("FAIL: network connectivity checks failed")
    print("PASS: both endpoints communicate with zero packet loss")


if __name__ == "__main__":
    main()
