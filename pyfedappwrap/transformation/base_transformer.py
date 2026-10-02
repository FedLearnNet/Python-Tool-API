import numbers
import pandas as pd
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar, Generic, Union, Any, Optional

from pyfedappwrap.learning.base_app import BaseApp
from pyfedappwrap.transformation.config.transformer_config import BaseTransformerConfig, \
    TransformerInputConfig, TransformerOutputConfig

VALUE_PREFIX = "[VALUE]"

TConfig = TypeVar('TConfig', bound=BaseTransformerConfig)


class BaseTransformerAPP(BaseApp[TConfig, TransformerInputConfig, TransformerOutputConfig], ABC,
                         Generic[TConfig]):

    def __init__(self):
        super().__init__()

    @abstractmethod
    def transform(self, data: Union[
        list[dict[str, Any]], dict[str, Union[str, int, float, bool]], Union[str, int, float, bool]]):
        pass

    def run_transformation(self, data: TransformerInputConfig) -> TransformerOutputConfig:
        self.logger.info("transformation started with the following data")
        if self.config.is_on_patient():
            self.logger.info("transformation on patient")
            dataframe = self.function_on_patient(data.input)
        elif self.config.is_on_row():
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
                              f"{str(e)}", exc_info=e)
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
                              f"{str(e)}", exc_info=e)
            return None

    def function_on_patient(self, df: pd.DataFrame):
        # pylint: disable=broad-exception-caught
        """
        Applies a function on all rows of one patient at once.

        The rows are grouped by ``patient_id_column`` (keeping the order in which patients
        first appear) and ``transform`` is called once per patient with a list of rows,
        each row holding the configured ``input_mapping`` parameters. The keys of each
        result dict are written back through ``return_mapping``, as for a row function.

        ``transform`` returns either a list of results or a tuple ``(results, row_order)``,
        where ``row_order`` names the source row index of each result. What is returned
        decides which rows survive:
          - one result per input row: every row is kept, a ``row_order`` reorders them;
          - fewer results than input rows: only the rows named by ``row_order`` are kept,
            in that order;
          - an empty list: the complete patient is removed.

        Args:
        df (pd.DataFrame): The DataFrame.

        Returns:
        pd.DataFrame: The DataFrame with the function applied.
        """
        try:
            patient_id_column = self.config.patient_id_column
            if not patient_id_column or patient_id_column not in df.columns:
                raise ValueError("Patient transformations require a column mapped to the "
                                 f"external patient id, got '{patient_id_column}'")
            patient_ids = df[patient_id_column]
            if patient_ids.isna().any() or (patient_ids.astype(str).str.strip() == "").any():
                raise ValueError(f"Row is missing the external patient id in column '{patient_id_column}'")

            patients = [self._apply_on_patient(patient_df)
                        for _, patient_df in df.groupby(patient_ids.astype(str), sort=False)]
            if not patients:
                return df.iloc[0:0]
            return pd.concat(patients, ignore_index=True)
        except Exception as e:
            self.logger.error(f"transform ({e.__class__.__name__}): "
                              f"{str(e)}", exc_info=e)
            return None

    def _apply_on_patient(self, patient_df: pd.DataFrame) -> pd.DataFrame:
        records = patient_df.to_dict("records")
        input_mapping = self.config.input_mapping or {}
        rows = [{param: self._resolve_patient_value(spec, record) for param, spec in input_mapping.items()}
                for record in records]

        result = self.transform(rows)
        results, row_order = result if isinstance(result, tuple) else (result, None)
        if results is None:
            raise ValueError("transform returned None instead of patient results")
        if len(results) == 0:
            return patient_df.iloc[0:0]
        if len(results) > len(records):
            raise ValueError("transform must not return more results than the patient has rows")
        if row_order is None:
            row_order = list(range(len(records)))
        row_order = list(row_order)
        if (len(row_order) != len(results) or len(set(row_order)) != len(results)
                or any(not isinstance(i, numbers.Integral) or i < 0 or i >= len(records) for i in row_order)):
            raise ValueError("transform returned an invalid patient row order")

        selected = patient_df.iloc[row_order].copy()
        for function_return, df_col in (self.config.return_mapping or {}).items():
            if df_col is None:
                continue
            current = selected[df_col].tolist() if df_col in selected.columns else [None] * len(results)
            # a None result leaves the row untouched
            selected[df_col] = [current[i] if r is None else r.get(function_return)
                                for i, r in enumerate(results)]
        return selected

    def _resolve_patient_value(self, spec: Optional[str], record: dict) -> Any:
        """A mapping to a column the row does not have yields None, never the column name."""
        if spec is None:
            return None
        if spec == VALUE_PREFIX:
            return None if self.config.column is None else record.get(self.config.column)
        if spec.startswith(VALUE_PREFIX):
            return spec[len(VALUE_PREFIX):]
        return record.get(spec)

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass
