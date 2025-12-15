"""
Artifact Store - Local filesystem implementation.

Implements the ArtifactStore port from services/pipeline/ports.py.
Provides safe, atomic file storage with content-addressable naming.
"""

from __future__ import annotations

import hashlib
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_component(value: str) -> str:
    """Sanitize a string for use in file paths."""
    value = value.strip() or "unnamed"
    return _SAFE_PATTERN.sub("_", value)[:64]


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when an artifact cannot be found."""

    pass


@dataclass(frozen=True)
class LocalArtifactStoreConfig:
    """Configuration for LocalArtifactStore."""

    base_dir: Path
    public_base_url: str | None = None


class ArtifactStoreBase(ABC):
    """
    Base class for artifact storage adapters.

    Matches the ArtifactStore port from services/pipeline/ports.py:
    - save(task_id, step, name, data) -> ref
    - load(ref) -> bytes
    - list(task_id, step) -> Sequence[ref]

    Concrete stores may optionally provide get_url(ref) for web-layer convenience.
    Pipeline code should not depend on URLs.
    """

    @abstractmethod
    def save(self, *, task_id: str, step: str, name: str, data: bytes) -> str:
        """Save artifact data and return a reference string."""
        ...

    @abstractmethod
    def load(self, *, ref: str) -> bytes:
        """Load artifact data by reference."""
        ...

    @abstractmethod
    def list(self, *, task_id: str, step: str) -> Sequence[str]:
        """List artifact references for a task/step."""
        ...

    def get_url(self, *, ref: str) -> str | None:
        """Get public URL for artifact (optional, web-layer convenience)."""
        return None


class LocalArtifactStore(ArtifactStoreBase):
    """
    Local filesystem artifact store.

    Features:
    - Atomic writes (write to temp, then rename)
    - Content-addressable naming (SHA256 suffix)
    - Path traversal protection
    - Optional public URL generation

    The `ref` is a relative path under base_dir, safe to persist in DB.
    """

    def __init__(self, config: LocalArtifactStoreConfig) -> None:
        self._base_dir = config.base_dir.resolve()
        self._public_base_url = config.public_base_url
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path: Path) -> None:
        """Ensure path is within base_dir (prevent path traversal)."""
        resolved = path.resolve()
        if self._base_dir not in resolved.parents and resolved != self._base_dir:
            raise ValueError("Artifact path resolved outside base_dir")

    def save(self, *, task_id: str, step: str, name: str, data: bytes) -> str:
        task_component = _safe_component(task_id)
        step_component = _safe_component(step)
        name_component = _safe_component(name)

        # Content-addressable: include hash in filename for deduplication
        digest = hashlib.sha256(data).hexdigest()[:16]
        filename = f"{name_component}-{digest}.bin"
        rel = f"{task_component}/{step_component}/{filename}"

        path = self._base_dir / rel
        self._validate_path(path)

        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to unique temp file, then rename
        import uuid as uuid_mod
        tmp_name = f".tmp-{uuid_mod.uuid4().hex}-{path.name}"
        tmp_path = path.parent / tmp_name
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        return rel

    def load(self, *, ref: str) -> bytes:
        path = self._base_dir / ref
        self._validate_path(path)

        try:
            return path.read_bytes()
        except FileNotFoundError as e:
            raise ArtifactNotFoundError(f"Artifact not found: {ref}") from e

    def list(self, *, task_id: str, step: str) -> Sequence[str]:
        task_component = _safe_component(task_id)
        step_component = _safe_component(step)
        dir_path = self._base_dir / task_component / step_component

        self._validate_path(dir_path)

        if not dir_path.exists():
            return []

        refs: list[str] = []
        for entry in dir_path.iterdir():
            if entry.is_file() and not entry.name.endswith(".tmp"):
                refs.append(f"{task_component}/{step_component}/{entry.name}")

        return sorted(refs)

    def get_url(self, *, ref: str) -> str | None:
        if not self._public_base_url:
            return None
        return f"{self._public_base_url.rstrip('/')}/{ref}"

    def delete(self, *, ref: str) -> bool:
        """Delete an artifact by reference. Returns True if deleted."""
        path = self._base_dir / ref
        self._validate_path(path)

        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def exists(self, *, ref: str) -> bool:
        """Check if an artifact file exists."""
        path = self._base_dir / ref
        self._validate_path(path)
        return path.is_file()
