from pydantic.dataclasses import dataclass
from pyfedappwrap.types.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.types.transformation.transformer_config import BaseTransformerConfig


@dataclass
class TransformerConfig(BaseTransformerConfig):
    pass


class MyTest(BaseTransformerAPP[TransformerConfig]):
    def __init__(self):
        super().__init__()

    def transform(self, value: str) -> str:
        # TODO Implement a simple transformation, e.g., converting to uppercase
        # Like return value.upper()
        pass