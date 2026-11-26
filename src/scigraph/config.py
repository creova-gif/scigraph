import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SciGraphConfig(BaseModel):
    """Project-level configuration loaded from ``scigraph.toml``."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    default_store: str | None = None
    workspace_root: str | None = None
    default_org: str = "default-org"
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8765, ge=1, le=65535)
    rate_limit: int | None = Field(default=None, ge=1)
    rate_window_seconds: float = Field(default=60.0, gt=0.0)


def load_scigraph_config(path: Path | None = None) -> SciGraphConfig:
    """Load and validate SciGraph configuration from a TOML file.

    When ``path`` is ``None``, looks for ``scigraph.toml`` in the current working
    directory and returns default configuration if it does not exist.
    When ``path`` is provided, raises ``ValueError`` if it is missing or a directory.
    """
    if path is None:
        target = Path("scigraph.toml")
        if not target.exists():
            return SciGraphConfig()
    else:
        target = path
        if not target.exists():
            raise ValueError(f"Config path does not exist: {target}")

    if target.is_dir():
        raise ValueError(f"Config path is a directory: {target}")

    raw_text = target.read_text(encoding="utf-8")
    try:
        parsed: dict[str, Any] = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {target}: {exc}") from exc

    if "scigraph" in parsed:
        section_obj: object = parsed["scigraph"]
        if not isinstance(section_obj, dict):
            raise ValueError(f"Expected [scigraph] table in {target}")
        section: dict[str, Any] = section_obj
    else:
        section = parsed

    try:
        return SciGraphConfig.model_validate(section, strict=False)
    except ValidationError as exc:
        raise ValueError(f"Invalid SciGraph configuration in {target}: {exc}") from exc
