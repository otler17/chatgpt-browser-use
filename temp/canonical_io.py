from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def encode_utf8_lf(text: str) -> bytes:
    """Return the exact portable byte representation used by integrity checks."""
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def canonical_json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def canonical_json_bytes(payload: Any) -> bytes:
    return encode_utf8_lf(canonical_json_text(payload))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text_lf(text: str) -> str:
    return sha256_bytes(encode_utf8_lf(text))


def sha256_json(payload: Any) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def write_bytes_atomic(path: str | Path, payload: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.tmp")
    temp.write_bytes(payload)
    temp.replace(target)
    return target


def write_text_lf(path: str | Path, text: str) -> Path:
    return write_bytes_atomic(path, encode_utf8_lf(text))


def write_json_lf(path: str | Path, payload: Any) -> Path:
    return write_bytes_atomic(path, canonical_json_bytes(payload))


def canonical_text_artifact(
    name: str,
    text: str,
    *,
    media_type: str = "text/plain",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = encode_utf8_lf(text)
    artifact: dict[str, Any] = {
        "name": str(name),
        "media_type": str(media_type),
        "encoding": "utf-8",
        "newline": "lf",
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "content": payload.decode("utf-8"),
    }
    if metadata:
        artifact["metadata"] = dict(metadata)
    return artifact
