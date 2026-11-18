from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import stat
import uuid
from pathlib import Path

from .models import BackupRecord


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_backup_id(base: Path) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:19]
    if not (base / stamp).exists():
        return stamp
    for _ in range(16):
        candidate = f"{stamp}-{uuid.uuid4().hex[:6]}"
        if not (base / candidate).exists():
            return candidate
    sequence = 1
    while (base / f"{stamp}-{sequence}").exists():
        sequence += 1
    return f"{stamp}-{sequence}"


def backup_file(backup_root: Path, source: Path, relative: str) -> BackupRecord:
    relative = relative.replace("\\", "/")
    target = backup_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    digest = sha256_file(target)
    file_path = relative.split("/", 1)[1] if "/" in relative else relative
    return BackupRecord(
        file_path=file_path,
        backup_path=f"{backup_root.name}/{relative}",
        captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        after_sha256=digest,
    )


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    temp = path.with_name(f".{path.name}.repoguard.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if mode is not None:
            os.chmod(path, mode)
    except Exception:
        try:
            temp.unlink()
        except OSError:
            pass
        raise