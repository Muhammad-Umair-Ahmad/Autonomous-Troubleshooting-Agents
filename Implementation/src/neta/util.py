import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(obj):
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + '\n')
    tmp.replace(path)

def run(args, timeout=90, check=True, **kwargs):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, **kwargs)
    if check and p.returncode:
        raise RuntimeError(f'{args[0]} rc={p.returncode}: {p.stdout[-2000:]} {p.stderr[-2000:]}')
    return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
