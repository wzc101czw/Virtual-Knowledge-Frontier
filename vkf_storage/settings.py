"""Per-database, credential-free VKF settings (UTF-8 JSON)."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4
from .core import InvalidInput, Conflict

DEFAULTS = {
    "vault": "", "model": "", "api_base": "https://api.openai.com/v1",
    "timeout": 60, "extract": "heuristic", "compare": "heuristic",
}


def _setting_path(db_path: str | Path) -> Path:
    path = Path(db_path).expanduser().resolve()
    if str(db_path) == ":memory:":
        raise InvalidInput("settings require a persistent database")
    return path.with_name(path.name + ".settings.json")


def _validate(key: str, value: object):
    if key not in DEFAULTS:
        raise InvalidInput("unknown setting: " + str(key) + "; API keys must stay in VKF_API_KEY environment variable")
    if not isinstance(value, str) and key != "timeout":
        raise InvalidInput(f"{key} must be text")
    if key == "vault":
        if not value or not Path(value).expanduser().is_dir():
            raise InvalidInput("vault must be an existing directory opened by Obsidian")
        value = str(Path(value).expanduser().resolve())
    elif key == "model":
        if len(value) > 200 or "\n" in value or "\r" in value:
            raise InvalidInput("invalid model id")
    elif key == "api_base":
        p = urlsplit(value)
        if not (p.scheme == "https" or (p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1"})):
            raise InvalidInput("api_base must use HTTPS or localhost HTTP")
        if not p.netloc or p.username or p.password or p.query or p.fragment or any(c.isspace() for c in value):
            raise InvalidInput("invalid or unsafe API URL")
        value = value.rstrip("/")
    elif key == "timeout":
        try:
            value = int(value)
        except (ValueError, TypeError):
            raise InvalidInput("timeout must be an integer between 5 and 600")
        if not 5 <= value <= 600:
            raise InvalidInput("timeout must be an integer between 5 and 600")
    elif key == "extract":
        if value not in {"none", "heuristic", "llm"}:
            raise InvalidInput("extract must be none|heuristic|llm")
    elif key == "compare":
        if value not in {"heuristic", "llm"}:
            raise InvalidInput("compare must be heuristic|llm")
    return value


def load_settings(db_path: str | Path) -> dict:
    path = _setting_path(db_path)
    if path.is_symlink():
        raise Conflict("refusing symlink settings file")
    if not path.exists():
        return dict(DEFAULTS)
    if path.stat().st_size > 1024 * 1024:
        raise InvalidInput("settings file is unexpectedly large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"settings file is invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict) or any(key not in DEFAULTS for key in data):
        raise InvalidInput("settings file has unknown fields; secrets must not be stored here")
    result = dict(DEFAULTS)
    for key, value in data.items():
        result[key] = _validate(key, value) if value or key != "vault" else ""
    return result


def save_setting(db_path: str | Path, key: str, value: object) -> dict:
    path = _setting_path(db_path)
    config = load_settings(db_path)
    config[key] = _validate(key, value)
    if path.is_symlink():
        raise Conflict("refusing symlink settings file")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid4().hex[:8])
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"path": str(path), "settings": config, "api_key_saved": False}
