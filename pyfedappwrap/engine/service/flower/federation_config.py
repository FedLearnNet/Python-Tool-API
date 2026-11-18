"""Ensures a `[superlink.<name>]` entry exists in Flower's own Configuration file
(`$FLWR_HOME/config.toml`, default `~/.flwr/config.toml`) so `flwr run`/`flwr list` have a named
SuperLink connection to target.

Confirmed empirically (read in full, then verified by actually running `flwr config list` and
inspecting the file Flower itself generated) that this - not `pyproject.toml`'s older
`[tool.flwr.federations.<name>]` - is where connection details live on the actually-installed
latest Flower release. Only ever writes our own fixed-name entry, pointed at the aggregator's
own embedded SuperLink (`127.0.0.1:<port>`, loopback only, so `insecure` is fine regardless of
whether the Fleet API facing clinics uses TLS) - never touches any other section a developer or
`flwr` itself may have written.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

FEDERATION_NAME = "flnet-local"

_SECTION_RE = re.compile(
    r"\n?\[superlink\." + re.escape(FEDERATION_NAME) + r"\]\n(?:[^\[].*\n?)*"
)


def flwr_home() -> Path:
    """Mirrors Flower's own resolution order: $FLWR_HOME, then $XDG_DATA_HOME/.flwr, else
    ~/.flwr."""
    if os.environ.get("FLWR_HOME"):
        return Path(os.environ["FLWR_HOME"])
    if os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / ".flwr"
    return Path.home() / ".flwr"


def config_toml_path() -> Path:
    return flwr_home() / "config.toml"


def ensure_local_federation(port: int, *, name: str = FEDERATION_NAME) -> str:
    """Idempotently points `[superlink.<name>]` at 127.0.0.1:<port>. Returns `name`."""
    path = config_toml_path()
    section = f"[superlink.{name}]\naddress = \"127.0.0.1:{port}\"\ninsecure = true\n"

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    without_section = _SECTION_RE.sub("", existing).rstrip("\n")

    if "[superlink]" in without_section:
        new_content = without_section + "\n\n" + section
    else:
        new_content = f"[superlink]\ndefault = \"{name}\"\n\n" + without_section.lstrip("\n")
        new_content = new_content.rstrip("\n") + "\n\n" + section

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    return name
