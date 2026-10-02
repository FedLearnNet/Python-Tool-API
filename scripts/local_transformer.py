from typing import Any

from pydantic.dataclasses import dataclass

from pyfedappwrap.types.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.types.transformation.transformer_config import BaseTransformerConfig


@dataclass
class TransformerConfig(BaseTransformerConfig):
    delimiter: str = '|'


class TransformerCombineRows(BaseTransformerAPP[TransformerConfig]):
    def __init__(self):
        super().__init__()

    def transform(self, row) -> dict[str, str | Any]:
        """
           Split a string value from the input row using the specified delimiter.

           Args:
               row (dict): Input dictionary containing a 'value' key with the string to split

           Returns:
               dict: Dictionary containing two parts of the split string with keys 'a' and 'b'

           Examples:
               >>> split_string({'value': 'hello|world'})
               {'a': 'hello', 'b': 'world'}
           """
        value = row['value']
        parts = value.split(self.config.delimiter)
        a, b = parts[0], parts[1] if len(parts) > 1 else ''
        self.logger.debug("Split Row")
        return {'a': a, 'b': b}
