import logging
import random
import string
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional

from pyfedappwrap.engine.helper.value_helper import value_to_str
from pyfedappwrap.generator.helper import (
    gen_matching_text,
    parse_float_or_default,
    parse_int_or_default,
    random_date,
    random_datetime,
    random_float,
    random_int,
    random_text,
)
from pyfedappwrap.transformation.validate.datatype_dto import (
    DataTypes,
    DataTypeTransformationGoalDTO,
    DataTypeValidationType,
)
from pyfedappwrap.transformation.validate.validate import is_valid_value, normalize_value, validate

V = DataTypeValidationType


class DataTypeRandomGenerator:

    def __init__(self, seed: Optional[int] = None):
        self.rnd = random.Random(seed)

    def generate_data(
            self,
            source_goals: Dict[str, DataTypeTransformationGoalDTO],
            amount: int = 10,
    ) -> Dict[str, List[str]]:
        data: Dict[str, List[str]] = {}
        for col_name, goal in source_goals.items():
            try:
                data[col_name] = self.generate_dummy_data(goal, amount)
            except ValueError as e:
                raise ValueError(f"Invalid goal for column '{col_name}': {e}") from e
        return data

    def generate_dummy_data(
            self,
            data_type: DataTypeTransformationGoalDTO,
            amount: int,
            max_attempts: int = 10,
    ) -> List[str]:
        validate(data_type)
        generated: List[str] = []
        for _ in range(amount):
            value = self.generate_random_value(data_type)
            attempts = 0
            while not is_valid_value(value, data_type) and attempts < max_attempts:
                value = self.generate_random_value(data_type)
                attempts += 1
            if attempts >= max_attempts and not is_valid_value(value, data_type):
                logging.debug(
                    f"No valid {data_type.type.value} value after {max_attempts} attempts, keeping {value!r}")
            generated.append(value_to_str(value))
        return generated

    def generate_random_value(self, data_type: DataTypeTransformationGoalDTO) -> Any:
        if data_type.options:
            return self.rnd.choice(data_type.options)

        validations = validations_to_map(data_type)

        t = data_type.type
        if t == DataTypes.INT:
            lo = parse_int_or_default(validations.get(V.MIN), 0)
            hi = parse_int_or_default(validations.get(V.MAX), 100)
            return random_int(self.rnd, lo, hi)
        if t == DataTypes.FLOAT:
            lo = parse_float_or_default(validations.get(V.MIN), 0.0)
            hi = parse_float_or_default(validations.get(V.MAX), 100.0)
            return random_float(self.rnd, lo, hi)
        if t == DataTypes.BOOLEAN:
            return self.rnd.random() < 0.5
        if t == DataTypes.STRING:
            pattern = validations.get(V.PATTERN)
            if pattern:
                v = gen_matching_text(pattern, self.rnd)
                if v is not None:
                    return v
            min_len = parse_int_or_default(validations.get(V.MINLENGTH), 1)
            max_len = parse_int_or_default(validations.get(V.MAXLENGTH), min_len + 10)
            return self._random_lowercase(min_len, max_len)
        if t in (DataTypes.DATE, DataTypes.DATE_TIME):
            if V.MIN in validations or V.MAX in validations:
                return self._random_between(validations, t).isoformat()
            return (random_date if t == DataTypes.DATE else random_datetime)(self.rnd).isoformat()
        if t == DataTypes.CATEGORICAL:
            return self._random_lowercase(3, 8)
        if t == DataTypes.FILE:
            return self._random_lowercase(8, 8) + ".txt"
        raise ValueError(f"Unsupported data type: {t}")

    def wide_format_to_long_format(self, data: List[Mapping[str, str]]) -> List[Dict[str, str]]:
        """Explode wide rows into one long row per column, each tagged with random patient/visit ids."""
        long_rows: List[Dict[str, str]] = []
        if not data:
            return long_rows

        max_patient_ids = max(1, len(data) // 5)

        for row in data:
            patient_id = random_int(self.rnd, 1, max_patient_ids)
            visit_id = random_int(self.rnd, 1_000, 999_999)
            visit_ts = random_datetime(self.rnd).isoformat() + "Z"

            for key, value in row.items():
                long_rows.append({
                    "id": str(random_int(self.rnd, 1, 1_000_000_000)),
                    "patientId": str(patient_id),
                    "name": key,
                    "value": value,
                    "visitId": str(visit_id),
                    "visitTimestamp": visit_ts,
                    "visitTimestampFormat": "ISO-8601",
                })

        return long_rows

    def _random_between(self, validations: Dict[DataTypeValidationType, str], t: DataTypes) -> date:
        """Random date/datetime within MIN/MAX; a missing bound lies ten years from the given one."""
        span = timedelta(days=3650)
        lo = normalize_value(validations.get(V.MIN), t)
        hi = normalize_value(validations.get(V.MAX), t)
        lo = lo or hi - span
        hi = hi or lo + span
        # adding a timedelta to a date only adds its whole days
        return lo + timedelta(seconds=random_int(self.rnd, 0, int((hi - lo).total_seconds())))

    def _random_lowercase(self, min_len: int, max_len: int) -> str:
        return random_text(self.rnd, min_len, max(min_len, max_len), string.ascii_lowercase)


def validations_to_map(data_type: DataTypeTransformationGoalDTO) -> Dict[DataTypeValidationType, str]:
    return {v.name: v.validator for v in data_type.validations}
