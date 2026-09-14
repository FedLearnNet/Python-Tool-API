import logging
import os
import random
import shutil
import string
import uuid
from pathlib import Path
from typing import Optional, Any

from pyfedappwrap.engine.config.config import ToolConfigDataType, \
    FederatedAppBaseConfigDTO
from pyfedappwrap.engine.config.config_handler import load_config
from pyfedappwrap.engine.config.defaults import DEFAULT_TABULAR_SCHEMA
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.generator.html_generator import generate_random_html
from pyfedappwrap.engine.generator.image_generator import generate_random_image
from pyfedappwrap.engine.generator.json_generator import generate_random_json
from pyfedappwrap.engine.generator.table_generator import generate_random_csv_from_schema

ROOT_DIR = Path(os.path.abspath(os.curdir))
BASE_PATH = ROOT_DIR / system_settings.data_dir

class RandomTestGeneratorFactory:

    def __init__(self):
        self.config = load_config(system_settings.config_settings_path)
        self.hyperparams: Optional[Any] = None
        if self.config is None:
            raise ValueError(f"Failed to load config file: {system_settings.config_settings_path}")
        self.input_configs = self.config.appConfig.input
        self.manged_generators: dict[str, RandomTestGenerator] = {}

    def has_manged_generator(self) -> bool:
        return len(self.manged_generators) > 0

    def mange_all(self):
        for input_cfg in self.input_configs:
            if input_cfg.name not in self.manged_generators:
                generator = RandomTestGenerator(input_cfg)
                self.manged_generators[input_cfg.name] = generator

    def mange_by_name(self, name: str):
        for input_cfg in self.input_configs:
            if input_cfg.name == name:
                generator = RandomTestGenerator(input_cfg)
                self.manged_generators[input_cfg.name] = generator

    def generate(self) -> dict[str, Path]:
        generated_files: dict[str, Path] = {}
        for name, generator in self.manged_generators.items():
            if generator.generated_path is not None and generator.generated_path.exists():
                logging.info(f"File for '{name}' already generated at {generator.generated_path}, skipping generation.")
                generated_files[name] = generator.generated_path
                continue
            generated_path = generator.generate()
            generated_files[name] = generated_path
        return generated_files

    def generate_first(self) -> Optional[Path]:
        for name, generator in self.manged_generators.items():
            generated_path = generator.generate()
            return generated_path
        return None

    def generate_by_name(self, name: str) -> Optional[Path]:
        generator = self.manged_generators.get(name)
        if generator is not None:
            generated_path = generator.generate()
            return generated_path
        return None

    def path_name(self, name: str) -> Optional[Path]:
        generator = self.manged_generators.get(name)
        if generator is not None and generator.generated_path is not None:
            return generator.generated_path
        return self.generate_by_name(name)

    def clean_up(self):
        for name, generator in self.manged_generators.items():
            if generator.generated_path and generator.generated_path.exists():
                logging.info(f"Deleting test file {generator.generated_path} for: {name}")
                if generator.generated_path and os.path.exists(generator.generated_path):
                    logging.info(f"Deleting test file {generator.generated_path} for: {name}")
                    generator.generated_path.unlink()

    def copy_for_predefined(self, predefined: dict[str, Path]) -> dict[str, Path]:
        """Copy predefined input files into the local BASE_PATH and register them.
        """
        copied: dict[str, Path] = {}

        for input_cfg in self.input_configs:
            name = input_cfg.name
            if name not in predefined:
                continue

            src = predefined[name]
            if src is None or not Path(src).exists():
                logging.warning(f"Predefined path for '{name}' does not exist: {src}")
                continue
            generator = self.manged_generators.get(name)
            if generator is None:
                generator = RandomTestGenerator(input_cfg)
            BASE_PATH.mkdir(parents=True, exist_ok=True)
            dest = BASE_PATH / Path(src).name
            if dest.exists():
                dest = BASE_PATH / f"{Path(src).stem}_{_short_uuid4()}{Path(src).suffix}"
            shutil.copy2(src, dest)
            generator.generated_path = dest
            self.manged_generators[name] = generator
            copied[name] = dest
        return copied

class RandomTestGenerator:
    """
    Generates a random test file for the given *input config* (as-is).
    It does NOT invent/modify config values; it only chooses an appropriate generator
    and writes the resulting file to cfg.out_dir.
    """

    def __init__(self, cfg: FederatedAppBaseConfigDTO):
        self.cfg = cfg

        self.seed = random.randint(0, 2 ** 32 - 1)
        self.generated_path: Optional[Path] = None

        if self.cfg.type == ToolConfigDataType.TSV:
            self.delimiter = "\t"
        elif self.cfg.type == ToolConfigDataType.CSV:
            self.delimiter = self.cfg.delimiter or ","
        else:
            self.delimiter = self.cfg.delimiter or ","

    def generate(self) -> Path:
        t = self.cfg.type
        suffix = _short_uuid4()

        if t in (ToolConfigDataType.CSV, ToolConfigDataType.TSV):
            schema = self.cfg.tabularSchema
            if schema is None:
                schema = DEFAULT_TABULAR_SCHEMA
                logging.info(f"No schema found for {t}, using default schema.")

            out = BASE_PATH / f"random_{self.cfg.name}_{suffix}.{t.value.lower()}"
            self.generated_path = generate_random_csv_from_schema(
                schema=schema,
                out_path=out,
                delimiter=self.delimiter,
                seed=self.seed,
                include_header=bool(self.cfg.hasHeader if self.cfg.hasHeader is not None else True),
            )
            return self.generated_path

        if t == ToolConfigDataType.JSON:
            out = BASE_PATH / f"random_{self.cfg.name}_{suffix}.json"
            self.generated_path = generate_random_json(out, seed=self.seed)
            return self.generated_path

        if t == ToolConfigDataType.HTML:
            out = BASE_PATH / f"random_{self.cfg.name}_{suffix}.html"
            self.generated_path = generate_random_html(out, seed=self.seed)
            return self.generated_path

        if t == ToolConfigDataType.IMAGE:
            out = BASE_PATH / f"random_{self.cfg.name}_{suffix}.png"
            self.generated_path = generate_random_image(out, seed=self.seed)
            return self.generated_path

        out = BASE_PATH / f"random_{self.cfg.name}_{suffix}.txt"
        self.generated_path = generate_random_text(out, seed=self.seed)
        return self.generated_path


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

    alphabet = string.ascii_letters + string.digits + " _-.:/@"

    with out_path.open("w", encoding="utf-8") as f:
        for _ in range(line_count):
            ln = rnd.randint(min_line_length, max_line_length)
            line = "".join(rnd.choice(alphabet) for _ in range(ln))
            f.write(line.rstrip() + "\n")

    return out_path


def _short_uuid4() -> str:
    return uuid.uuid4().hex[:8]
