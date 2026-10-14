# Code Transformer Runtime

Prebuilt runner the local learning API starts through orch and reuses to check custom ETL
transformation code. It answers `TRANSFORMATION_CHECK` messages with a
`TRANSFORMATION_CHECK_RESULT`: the code is checked statically, built and run against preview
rows or generated data, and every result is validated against the goal data type.

`TRANSFORMATION_SAVE` checks the code again and answers with a `TRANSFORMATION_SAVE_RESULT` holding
the generated project (`code_transformer.py`, `main.py`, `test.json`, `app.yml` and a `Dockerfile`
based on this image). The Tool-Build-Pipeline builds it locally, in test mode `main.py` tests the code
against `test.json`.

## Image

CI publishes it with the other images of this repository, versioned with pyfedappwrap
(`.github/workflows/docker.yml`): `ghcr.io/fedlearnnet/python-tool-api/code-transformer-runtime:<version>`
and `:latest`, built on `base-python-dep` of the same version.

Local build from the repository root, against a published base image:

```bash
docker build -f docker/Dockerfile.code-transformer-runtime \
  --build-arg BASE_IMAGE=ghcr.io/fedlearnnet/python-tool-api/base-python-dep:latest \
  -t ghcr.io/fedlearnnet/python-tool-api/code-transformer-runtime:dev .
```

## Test

```bash
cd code-transformer-runtime && python -m pytest
```
