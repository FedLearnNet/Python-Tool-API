import csv
import io
import logging
import random
import re
import string
from typing import Any, Dict, List, Mapping, Optional

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
from pyfedappwrap.transformation.datatype_dto import (
    DataTypes,
    DataTypeTransformationGoalDTO,
    DataTypeValidationType,
)

V = DataTypeValidationType


class DataTypeRandomGenerator:

    def __init__(self, seed: Optional[int] = None):
        self.rnd = random.Random(seed)

    def generate_dummy_data(
            self,
            data_type: DataTypeTransformationGoalDTO,
            amount: int,
            max_attempts: int = 10,
    ) -> List[str]:
        """Generate ``amount`` values, regenerating up to ``max_attempts`` times until one validates."""
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
        if t == DataTypes.DATE:
            return random_date(self.rnd).isoformat()
        if t == DataTypes.DATE_TIME:
            return random_datetime(self.rnd).isoformat()
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

    def _random_lowercase(self, min_len: int, max_len: int) -> str:
        return random_text(self.rnd, min_len, max(min_len, max_len), string.ascii_lowercase)


def validations_to_map(data_type: DataTypeTransformationGoalDTO) -> Dict[
    DataTypeValidationType, str]:
    return {v.name: v.validator for v in data_type.validations if v.validator is not None}


def is_valid_value(value: Any, data_type: DataTypeTransformationGoalDTO) -> bool:
    """Check a generated value against the options and MIN/MAX/MINLENGTH/MAXLENGTH/PATTERN validations."""
    if data_type.options:
        return value in data_type.options

    validations = validations_to_map(data_type)

    if data_type.type in (DataTypes.INT, DataTypes.FLOAT):
        lo = validations.get(V.MIN)
        hi = validations.get(V.MAX)
        if lo is not None and value < parse_float_or_default(lo, float("-inf")):
            return False
        if hi is not None and value > parse_float_or_default(hi, float("inf")):
            return False
        return True

    if data_type.type == DataTypes.STRING:
        s = str(value)
        min_len = validations.get(V.MINLENGTH)
        max_len = validations.get(V.MAXLENGTH)
        if min_len is not None and len(s) < parse_int_or_default(min_len, 0):
            return False
        if max_len is not None and len(s) > parse_int_or_default(max_len, len(s)):
            return False
        pattern = validations.get(V.PATTERN)
        if pattern:
            try:
                return re.fullmatch(pattern, s) is not None
            except re.error:
                return True
        return True

    return True


def value_to_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def create_list_of_dicts(data: Mapping[str, List[str]]) -> List[Dict[str, Optional[str]]]:
    """Turn column lists ``{col: [v0, v1, ...]}`` into rows ``[{col: v0}, {col: v1}, ...]``."""
    if not data:
        return []
    amount = len(next(iter(data.values())))
    return [
        {key: values[i] if i < len(values) else None for key, values in data.items()}
        for i in range(amount)
    ]


def to_csv(data: List[Mapping[str, Any]]) -> str:
    """Serialise rows to CSV using the first row's keys as header."""
    if not data:
        return ""
    headers = list(data[0].keys())
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for row in data:
        writer.writerow(["" if row.get(h) is None else row.get(h) for h in headers])
    return buf.getvalue()
