"""Bounded immutable artifacts and safe text-only repository archives."""

import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath

from .tool_contracts import ArtifactRef

MAX_ARTIFACT = 262144
MAX_STORAGE = 32 * 1024 * 1024
MEDIA = {"text/plain", "text/markdown", "text/csv", "application/json", "application/zip", "text/x-diff"}


def safe_path(name):
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and "\x00" not in name
        and len(name) <= 200
    )


def archive(content):
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if len(z.infolist()) > 100:
                raise ValueError
            total = 0
            for item in z.infolist():
                if item.is_dir():
                    continue
                mode = item.external_attr >> 16
                total += item.file_size
                if (
                    not safe_path(item.filename)
                    or item.filename in result
                    or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
                    or item.flag_bits & 1
                    or item.file_size > 65536
                    or total > 1048576
                    or item.file_size > max(1, item.compress_size) * 100
                ):
                    raise ValueError
                data = z.read(item)
                result[item.filename] = data.decode("utf-8")
    except Exception:
        raise ValueError("invalid_repository_archive") from None
    if not result:
        raise ValueError("empty_repository_archive")
    return result


def validate(content, media, filename):
    if len(content) > MAX_ARTIFACT:
        raise ValueError("artifact_size_limit")
    if media not in MEDIA:
        raise ValueError("unsupported_media_type")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", filename):
        raise ValueError("invalid_filename")
    if media == "application/zip":
        archive(content)
    else:
        try:
            text = content.decode("utf-8")
            if "\x00" in text:
                raise ValueError
            if media == "application/json":
                json.loads(text)
        except Exception:
            raise ValueError("invalid_artifact_content") from None
    return hashlib.sha256(content).hexdigest()


def ref(row):
    return ArtifactRef(**{k: getattr(row, k) for k in ArtifactRef.model_fields})


def verify(row):
    if len(row.content) != row.size_bytes or hashlib.sha256(row.content).hexdigest() != row.sha256:
        raise ValueError("artifact_integrity_error")
    return row.content
