import random
import string
from pathlib import Path
from typing import Optional


def generate_random_html(
    out_path: Path,
    *,
    min_blocks: int = 5,
    max_blocks: int = 25,
    seed: Optional[int] = None,
) -> Path:
    """
    Generates a random but valid HTML file.

    Intended for TEXT / STRING / MIXED / UNKNOWN style pipelines
    where the payload happens to be HTML.
    """
    rnd = random.Random(seed)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    def rand_text(min_len=10, max_len=80) -> str:
        alphabet = string.ascii_letters + string.digits + " _-.,:"
        n = rnd.randint(min_len, max_len)
        return "".join(rnd.choice(alphabet) for _ in range(n))

    block_count = rnd.randint(min_blocks, max_blocks)

    blocks = []

    for _ in range(block_count):
        kind = rnd.choice(["p", "h2", "ul", "a", "code"])
        if kind == "p":
            blocks.append(f"<p>{rand_text()}</p>")
        elif kind == "h2":
            blocks.append(f"<h2>{rand_text(5, 30)}</h2>")
        elif kind == "ul":
            items = "".join(f"<li>{rand_text(5,30)}</li>" for _ in range(rnd.randint(2, 6)))
            blocks.append(f"<ul>{items}</ul>")
        elif kind == "a":
            blocks.append(f'<a href="https://example.com/{rnd.randint(1,999)}">{rand_text(5,25)}</a>')
        elif kind == "code":
            blocks.append(f"<pre><code>{rand_text(20,120)}</code></pre>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Random Test Document</title>
</head>
<body>
<h1>Random HTML Test</h1>

{chr(10).join(blocks)}

</body>
</html>
"""

    with out_path.open("w", encoding="utf-8") as f:
        f.write(html)

    return out_path