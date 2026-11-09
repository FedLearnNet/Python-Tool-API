from datetime import date, datetime

from pydantic import NonNegativeInt, TypeAdapter

from pyfedappwrap.transformation.validate.datatype_dto import DataTypes, DataTypeValidationType

ADAPTERS = {
    DataTypes.INT: TypeAdapter(int),
    DataTypes.FLOAT: TypeAdapter(float),
    DataTypes.DATE: TypeAdapter(date),
    DataTypes.DATE_TIME: TypeAdapter(datetime),
}
LENGTH_ADAPTER = TypeAdapter(NonNegativeInt)
APPLICABLE_TYPES = {
    DataTypeValidationType.MINLENGTH: (DataTypes.STRING,),
    DataTypeValidationType.MAXLENGTH: (DataTypes.STRING,),
    DataTypeValidationType.PATTERN: (DataTypes.STRING,),
    DataTypeValidationType.MIN: (DataTypes.INT, DataTypes.FLOAT, DataTypes.DATE,
                                 DataTypes.DATE_TIME),
    DataTypeValidationType.MAX: (DataTypes.INT, DataTypes.FLOAT, DataTypes.DATE,
                                 DataTypes.DATE_TIME),
}
