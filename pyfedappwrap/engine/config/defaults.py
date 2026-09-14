from pyfedappwrap.engine.config.config import TabularSchemaDTO

DEFAULT_TABULAR_SCHEMA = TabularSchemaDTO(
    minRows=10,
    maxRows=100,
    minColumns=10,
    maxColumns=100
)

DEFAULT_APP_COMM_TIMEOUT: float = 600.0  # 10 minutes

# Used special comm id in communicating with the controller that makes the controller use
# the automatic comm id system
AUTO_COMM_ID = "#AUTOMATIC"
