from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar, Generic, Union

import pandas as pd

from pyfedappwrap.learning.base_app import BaseApp
from pyfedappwrap.types.transformation.transformer_config import BaseTransformerConfig, \
    TransformerInputConfig, TransformerOutputConfig

TConfig = TypeVar('TConfig', bound=BaseTransformerConfig)


class BaseTransformerAPP(BaseApp[TConfig, TransformerInputConfig, TransformerOutputConfig], ABC,
                         Generic[TConfig]):

    def __init__(self):
        super().__init__()

    @abstractmethod
    def transform(self, data: Union[
        dict[str, Union[str, int, float, bool]], Union[str, int, float, bool]]):
        pass

    def run_transformation(self, data: TransformerInputConfig) -> TransformerOutputConfig:
        self.logger.info("transformation started with the following data")
        self.logger.info(data.input)
        if self.config.is_on_row():
            self.logger.info("transformation on row")
            dataframe = self.function_on_row(data.input)
        else:
            self.logger.info("transformation on cell")
            dataframe = self.function_on_cell(data.input)
        if dataframe is None:
            raise Exception("Transformation failed returned None")

        output_path = Path("output.csv")
        dataframe.to_csv(output_path, index=False)
        return TransformerOutputConfig(output=output_path)

    def run_train(self, data: TransformerInputConfig) -> TransformerOutputConfig:
        return self.run_transformation(data)

    def run_prediction(self, data: TransformerInputConfig) -> TransformerOutputConfig:
        return self.run_transformation(data)

    def function_on_row(self, df: pd.DataFrame, axis=1):
        # pylint: disable=broad-exception-caught, cell-var-from-loop
        """
        Applies a function on each row of a DataFrame.

        Args:
        df (pd.DataFrame): The DataFrame.
        function (Function): The function to be applied.
        axis (int): The axis along which the function is applied.

        Returns:
        pd.DataFrame: The DataFrame with the function applied.
        """
        try:
            if (self.config.input_mapping is None or
                    self.config.return_mapping is None):
                return df

            def apply_mapped_method(row):
                args = {function_param: (
                    col.replace('[VALUE]', '') if col.startswith('[VALUE]') else row[col])
                    for function_param, col in self.config.input_mapping.items()}
                return self.transform(args)

            results = df.apply(apply_mapped_method, axis=axis)

            for function_return, df_col in self.config.return_mapping.items():
                if isinstance(results.iloc[0], dict):
                    df[df_col] = results.apply(lambda x: x.get(function_return))
                else:
                    df[df_col] = results

            return df
        except Exception as e:
            self.logger.error(f"transform ({e.__class__.__name__}): "
                              f"{str(e)}", e)
            return None

    def function_on_cell(self, df: pd.DataFrame):
        # pylint: disable=broad-exception-caught
        """
        Applies a function on each cell of a DataFrame.

        Args:
        df (pd.DataFrame): The DataFrame.
        function (Function): The function to be applied.

        Returns:
        pd.DataFrame: The DataFrame with the function applied.
        """
        try:
            self.logger.info("transformation started with the following data")
            self.logger.info(df.head())
            if self.config.column is None:
                return df
            else:
                df[self.config.column] = df[self.config.column].apply(self.transform)
            return df
        except Exception as e:
            self.logger.error(f"transform ({e.__class__.__name__}): "
                              f"{str(e)}", e)
            return None

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass
