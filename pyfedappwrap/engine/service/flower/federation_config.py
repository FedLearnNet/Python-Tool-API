"""Ensures a `[superlink.<name>]` entry exists in Flower's own Configuration file
(`$FLWR_HOME/config.toml`, default `~/.flwr/config.toml`) so `flwr run`/`flwr list` have a named
SuperLink connection to target.

Confirmed empirically (read in full, then verified by actually running `flwr config list` and
inspecting the file Flower itself generated) that this - not `pyproject.toml`'s older
`[tool.flwr.federations.<name>]` - is where connection details live on the actually-installed
latest Flower release. Only ever writes our own fixed-name entry, pointed at the aggregator's
own embedded SuperLink (`127.0.0.1:<port>`) - never touches any other section a developer or
`flwr` itself may have written.

Loopback is NOT automatically exempt from TLS: a SuperLink's Control/Runtime/Fleet APIs all
share one port and one TLS configuration (confirmed empirically by starting a real
`flower-superlink` with `--ssl-certfile`/`--ssl-keyfile`/`--ssl-ca-certfile` and observing that
`flwr run`/`flwr list` against it over loopback with `insecure = true` fails with "Connection to
the SuperLink is unavailable", while the identical call with `root-certificates` set to the same
CA succeeds) - this corrects an earlier, untested assumption in this module. Once the SuperLink
this federation entry targets runs with TLS enabled, `ca_certfile` must be passed here too.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

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


def ensure_local_federation(port: int, *, name: str = FEDERATION_NAME,
                             ca_certfile: Optional[Path] = None) -> str:
    """Idempotently points `[superlink.<name>]` at 127.0.0.1:<port>. Returns `name`. Pass
    `ca_certfile` when the SuperLink at that port is running with TLS enabled - see the module
    docstring for why loopback still needs this."""
    path = config_toml_path()
    if ca_certfile is not None:
        connection = f"root-certificates = \"{ca_certfile}\""
    else:
        connection = "insecure = true"
    section = f"[superlink.{name}]\naddress = \"127.0.0.1:{port}\"\n{connection}\n"

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
