from pydantic import BaseModel


class TransformationFactoryTestResultDTO(BaseModel):
    is_success: bool
    message: str