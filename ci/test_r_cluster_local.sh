#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

BASE_IMAGE="gitlab.cosy.bio:5050/cosybio/federated-learning/federated_db/pyfedappwrap/base-r-dep:latest"
PLATFORM="linux/arm64/v8"
IMAGE_TAG="pyfedappwrap/base-r-dep-cluster:local-test"
BUILDER_NAME="fedDBBuilder-local"

if docker buildx inspect "${BUILDER_NAME}" >/dev/null 2>&1; then
  docker buildx use "${BUILDER_NAME}"
else
  docker buildx create --name "${BUILDER_NAME}" --use
fi
docker buildx inspect --bootstrap >/dev/null

echo "Building Dockerfile.base-r-cluster-chainguard locally"
echo "  platform:  linux/amd64,linux/arm64/v8"
echo "  base image:${BASE_IMAGE}"
echo "  image tag: ${IMAGE_TAG}"
echo "  output:    --load"

docker buildx build \
  --progress=plain \
  --platform linux/amd64,linux/arm64/v8 \
  --provenance false \
  -f "${ROOT_DIR}/Dockerfile.base-r-cluster-chainguard" \
  --build-arg BASE_IMAGE="${BASE_IMAGE}" \
  -t "${IMAGE_TAG}" \
  "${ROOT_DIR}"

echo "Done. Local test build completed."
