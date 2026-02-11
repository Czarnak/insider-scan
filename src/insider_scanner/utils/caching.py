"""Simple file-based cache with TTL expiry."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from insider_scanner.utils.config import DEFAULT_CACHE_TTL
from insider_scanner.utils.logging import get_logger

log = get_logger("caching")


def cache_key(url: str) -> str:
    """Create a filesystem-safe cache key from a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def get_cached(cache_dir: Path, key: str, ttl: int = DEFAULT_CACHE_TTL) -> str | None:
    """Return cached content if it exists and hasn't expired, else None."""
    path = cache_dir / f"{key}.txt"
    meta_path = cache_dir / f"{key}.meta"

    if not path.exists() or not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text())
        ts = meta.get("timestamp", 0)
        if time.time() - ts > ttl:
            log.debug("Cache expired for %s", key)
            return None
    except (json.JSONDecodeError, KeyError):
        return None

    return path.read_text(encoding="utf-8")


def set_cached(cache_dir: Path, key: str, content: str) -> None:
    """Write content to cache with current timestamp."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.txt"
    meta_path = cache_dir / f"{key}.meta"

    path.write_text(content, encoding="utf-8")
    meta_path.write_text(json.dumps({"timestamp": time.time()}))
    log.debug("Cached %d chars for %s", len(content), key)


def clear_cache(cache_dir: Path) -> int:
    """Remove all cached files. Returns number of files removed."""
    count = 0
    if cache_dir.exists():
        for f in cache_dir.iterdir():
            if f.suffix in (".txt", ".meta"):
                f.unlink()
                count += 1
    return count
