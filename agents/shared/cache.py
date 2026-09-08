"""
File-backed cache for Gemini and TTS model responses.

Keyed by a SHA-256 hash of the call inputs. Cache files live in
demo/cache/ by default, overridable via EARSIGHT_CACHE_DIR.

Usage:
    from agents.shared.cache import cached

    @cached("tts")
    def synthesise(text: str) -> bytes:
        ...  # expensive TTS call

Enable with EARSIGHT_USE_CACHE=1.
"""

import functools
import hashlib
import inspect
import json
import os
import pickle
from pathlib import Path
from typing import Any, Callable, Optional, Sequence


_CACHE_DIR = Path(os.environ.get("EARSIGHT_CACHE_DIR", "demo/cache"))
_ENABLED = os.environ.get("EARSIGHT_USE_CACHE", "0") == "1"


def _key(*args, **kwargs) -> str:
    """Stable SHA-256 key from positional + keyword args."""
    raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _key_from_selected(fn: Callable, args: tuple, kwargs: dict, key_args: Sequence[str]) -> str:
    """Build a cache key from only the named parameters listed in key_args."""
    sig = inspect.signature(fn)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    selected = {name: bound.arguments[name] for name in key_args if name in bound.arguments}
    raw = json.dumps(selected, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def cached(namespace: str, key_args: Optional[Sequence[str]] = None) -> Callable:
    """
    Decorator that caches the return value of a function to disk.

    key_args: if provided, only these named parameters participate in the cache key.
              Use this to exclude arguments (e.g. a client object) whose repr is
              non-deterministic across processes.
    Only active when EARSIGHT_USE_CACHE=1.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            if not _ENABLED:
                return fn(*args, **kwargs)

            cache_dir = _CACHE_DIR / namespace
            cache_dir.mkdir(parents=True, exist_ok=True)
            if key_args is not None:
                key = _key_from_selected(fn, args, kwargs, key_args)
            else:
                key = _key(*args, **kwargs)
            cache_file = cache_dir / f"{key}.pkl"

            if cache_file.exists():
                with open(cache_file, "rb") as f:
                    print(f"[cache] hit: {namespace}/{key[:12]}")
                    return pickle.load(f)

            result = fn(*args, **kwargs)
            with open(cache_file, "wb") as f:
                pickle.dump(result, f)
            print(f"[cache] stored: {namespace}/{key[:12]}")
            return result

        return wrapper
    return decorator


def cache_dir_for(namespace: str) -> Path:
    """Return the cache directory for a namespace, creating it if needed."""
    d = _CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d
