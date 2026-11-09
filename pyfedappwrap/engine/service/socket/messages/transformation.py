from pyfedappwrap.transformation.factory.factory_test_result import TransformationFactoryTestResultDTO, \
    TransformationTestCaseDTO


class TransformationCheckDTO(TransformationTestCaseDTO):
    request_id: str
    body: str


class TransformationCheckResultDTO(TransformationFactoryTestResultDTO):
    request_id: str
    output: str = ""


class TransformationSaveDTO(TransformationCheckDTO):
    name: str
    description: str = ""
    base_image: str


class TransformationSaveResultDTO(TransformationFactoryTestResultDTO):
    request_id: str
    files: dict[str, str] = {}
