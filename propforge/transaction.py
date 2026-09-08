"""Recoverable publication of one complete output directory.

The lock is held by the OS, so process death releases it. Publication uses
same-volume renames. A journal covers the gap between moving the previous
directory aside and installing the candidate; the next run recovers it.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path


def _remove_owned(path: Path, parent: Path, prefix: str) -> None:
    resolved = path.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(prefix):
        raise ValueError(f"Unsicherer temporaerer Pfad: {path}")
    if path.is_symlink():
        raise ValueError(f"Temporärer Pfad ist ein Link: {path}")
    if path.exists():
        shutil.rmtree(path)


def relocate_json(root: Path, old: Path, new: Path) -> None:
    """Keep generated build records usable after their directory is renamed."""
    def relocate(value):
        if isinstance(value, str):
            for before, after in ((str(old), str(new)), (old.as_posix(), new.as_posix())):
                if value == before or value.startswith(before + os.sep) or value.startswith(before + "/"):
                    return after + value[len(before):]
            return value
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if isinstance(value, dict):
            return {k: relocate(v) for k, v in value.items()}
        return value
    for path in root.rglob("*.json"):
        original = json.loads(path.read_text(encoding="utf-8-sig"))
        updated = relocate(original)
        if updated != original:
            path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class DirectoryTransaction:
    def __init__(self, target: Path, *, seed: bool = True, relocate: bool = False):
        self.target = Path(target).resolve()
        if self.target.parent == self.target:
            raise ValueError("Ein Laufwerkswurzelverzeichnis ist kein Ausgabeordner.")
        self.parent = self.target.parent
        self.prefix = f".{self.target.name}.pf-"
        self.previous = self.parent / (self.prefix + "previous")
        self.journal = self.parent / (self.prefix + "journal.json")
        self.lock_path = self.parent / (self.prefix + "lock")
        self.seed, self.relocate = seed, relocate
        self.stage: Path | None = None
        self._lock = None

    def __enter__(self):
        self.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self.lock_path.open("a+b")
        try:
            self._lock.seek(0, os.SEEK_END)
            if self._lock.tell() == 0:
                self._lock.write(b"0")
                self._lock.flush()
            self._lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock.close()
            self._lock = None
            raise RuntimeError(f"Ausgabe ist durch einen anderen Lauf gesperrt: {self.target}") from exc
        try:
            self.recover()
            self.stage = Path(tempfile.mkdtemp(prefix=self.prefix + "stage-", dir=self.parent))
            if self.seed and self.target.exists():
                shutil.copytree(self.target, self.stage, dirs_exist_ok=True)
                if self.relocate:
                    relocate_json(self.stage, self.target, self.stage)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def recover(self) -> None:
        if not self.journal.exists():
            return
        data = json.loads(self.journal.read_text(encoding="utf-8"))
        if data.get("target") != str(self.target):
            raise RuntimeError(f"Unpassendes Wiederherstellungsjournal: {self.journal}")
        abandoned = Path(data["stage"])
        if (abandoned.resolve().parent != self.parent
                or not abandoned.name.startswith(self.prefix + "stage-") or abandoned.is_symlink()):
            raise RuntimeError(f"Unsicheres Wiederherstellungsjournal: {self.journal}")
        if not self.target.exists():
            if self.previous.is_dir():
                os.replace(self.previous, self.target)
            elif abandoned.is_dir():
                # First publication has no previous version to restore.
                os.replace(abandoned, self.target)
            else:
                raise RuntimeError(f"Unterbrochene Ausgabe ohne wiederherstellbare Vorversion: {self.target}")
        # Either the previous output was restored or the complete new output
        # was already installed before the process stopped.
        if abandoned.exists():
            _remove_owned(abandoned, self.parent, self.prefix + "stage-")
        self.journal.unlink()

    def publish(self) -> Path:
        if self.stage is None or not self.stage.is_dir():
            raise RuntimeError("Keine vorbereitete Ausgabe vorhanden.")
        if self.relocate:
            relocate_json(self.stage, self.stage, self.target)
        _remove_owned(self.previous, self.parent, self.prefix)
        data = {"version": 1, "target": str(self.target), "stage": str(self.stage)}
        pending_journal = self.journal.with_suffix(".pending")
        with pending_journal.open("w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending_journal, self.journal)
        if self.target.exists():
            os.replace(self.target, self.previous)
        try:
            os.replace(self.stage, self.target)
        except BaseException:
            if not self.target.exists() and self.previous.exists():
                os.replace(self.previous, self.target)
            raise
        self.journal.unlink()
        return self.target

    def __exit__(self, *_):
        try:
            if self.stage is not None and self.stage.exists():
                _remove_owned(self.stage, self.parent, self.prefix + "stage-")
        finally:
            if self._lock is not None:
                self._lock.close()
                self._lock = None
