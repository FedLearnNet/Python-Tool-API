import random
from pathlib import Path
from typing import Optional

from pyfedappwrap.generator.helper import random_text


def generate_random_text(
        out_path: Path,
        *,
        min_lines: int = 10,
        max_lines: int = 50,
        min_line_length: int = 5,
        max_line_length: int = 80,
        seed: Optional[int] = None,
) -> Path:
    """
    Generates a random text-based test file for:
      TEXT / STRING / MIXED / UNKNOWN

    Each line is a random ASCII string.

    Used for non-tabular validation pipelines.
    """
    rnd = random.Random(seed)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    line_count = rnd.randint(min_lines, max_lines)

    with out_path.open("w", encoding="utf-8") as f:
        for _ in range(line_count):
            line = random_text(rnd, min_line_length, max_line_length)
            f.write(line.rstrip() + "\n")

    return out_path
