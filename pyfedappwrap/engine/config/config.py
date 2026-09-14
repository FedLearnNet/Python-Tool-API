from dataclasses import field
from enum import Enum
from typing import List, Optional, Dict

from pydantic.dataclasses import dataclass
from pydantic.version import VERSION as PYDANTIC_VERSION

assert PYDANTIC_VERSION >= "2"


class AppType(str, Enum):
    POST_PROCESSING = "POST_PROCESSING"
    EVALUATION = "EVALUATION"
    PRE_PROCESSING = "PRE_PROCESSING"
    ANALYSIS = "ANALYSIS",
    SELF_LEARNED = "SELF_LEARNED"
    DATA_TRANSFORMATION = "DATA_TRANSFORMATION"
    EXTRACTOR = "EXTRACTOR"
    EXPORT = "EXPORT"


class ToolConfigDataType(str, Enum):
    HTML = "HTML"
    CSV = "CSV"
    TSV = "TSV"
    JSON = "JSON"
    IMAGE = "IMAGE"
    TEXT = "TEXT"
    STRING = "STRING"
    PATH = "PATH"
    UNKNOWN = "UNKNOWN"


class FederatedAppConfigHyperParamDataType(str, Enum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    CATEGORICAL = "CATEGORICAL"


class ModeType(str, Enum):
    TRAINING = "TRAINING"
    PREDICTION = "PREDICTION"
    VALIDATION = "VALIDATION"
    BOTH = "BOTH"


@dataclass
class NullValuePolicyDTO:
    # truly missing CSV fields (empty between delimiters), e.g. `a,,c`
    prohibitedEmptyCell: Optional[bool] = None

    # prohibited empty string values after parsing, e.g. "" (quoted empty)
    prohibitedEmptyString: Optional[bool] = None

    # prohibited whitespace-only strings like "   " (before/after trimming — define in backend)
    prohibitedWhitespaceString: Optional[bool] = None

    # prohibited string tokens that represent null (case-insensitive), e.g. "null", "none", "na"
    prohibitedNullLiterals: Optional[bool] = None

    # prohibited numeric NaN (actual NaN after parsing numeric columns)
    prohibitedNaN: Optional[bool] = None

    # prohibited 0 / 0.0 as a "null sentinel" (domain-specific)
    prohibitedZeroAsNull: Optional[bool] = None

    # Explicit list of null tokens
    # Used if prohibitedNullLiterals === true
    nullLiterals: Optional[List[str]] = None


@dataclass
class ColumnRuleDTO:
    type: Optional[FederatedAppConfigHyperParamDataType] = None
    nullable: Optional[bool] = None
    regex: Optional[str] = None
    enumValues: Optional[List[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    description: Optional[str] = None


@dataclass
class TabularSchemaDTO:
    minRows: Optional[int] = None
    maxRows: Optional[int] = None
    minColumns: Optional[int] = None
    maxColumns: Optional[int] = None

    allowOnlyNumbers: Optional[bool] = None
    prohibitedNulls: Optional[bool] = None
    nullPolicy: Optional[NullValuePolicyDTO] = None

    requiredColumns: Optional[List[str]] = None
    columns: Optional[Dict[str, ColumnRuleDTO]] = None


@dataclass
class FederatedAppHyperParamConfigDTO:
    name: str
    type: FederatedAppConfigHyperParamDataType
    description: str
    default: str | int | float
    options: List[str] = field(default_factory=list)
    minValue: Optional[float] = None
    maxValue: Optional[float] = None
    pattern: Optional[str] = None


@dataclass
class FederatedAppBaseConfigDTO:
    name: str
    type: ToolConfigDataType
    description: str
    minValue: Optional[float] = None
    maxValue: Optional[float] = None
    required: bool = False
    shape: Optional[str] = None
    tabularSchema: Optional[TabularSchemaDTO] = None
    delimiter: Optional[str] = ","
    hasHeader: Optional[bool] = True
    indexCol: Optional[int] = None
    mode: Optional[ModeType] = None


@dataclass
class FederatedAppInputConfigDTO(FederatedAppBaseConfigDTO):
    required: bool = False


@dataclass
class FederatedAppOutputConfigDTO(FederatedAppBaseConfigDTO):
    name: str


@dataclass
class LocalAppInfo:
    name: str
    slug: Optional[str]
    type: Optional[AppType]
    sourceUrl: Optional[str]
    shortDescription: Optional[str]
    longDescription: Optional[str]


@dataclass
class FederatedAppConfigDTO:
    hyperparams: List[FederatedAppHyperParamConfigDTO]
    input: List[FederatedAppInputConfigDTO]
    output: List[FederatedAppOutputConfigDTO]


@dataclass
class LocalAppConfig:
    config: FederatedAppConfigDTO
    info: LocalAppInfo


@dataclass
class FederatedAppDTO(LocalAppInfo):
    appConfig: FederatedAppConfigDTO
