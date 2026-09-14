#!/usr/bin/env sh
set -eu

IMAGE_FAMILY="${1:?missing image family, e.g. base-python}"
VERSION="${2:?missing version}"
WITH_DEPS="${3:-0}"
REGISTRY_IMAGE="${4:?missing registry image path, e.g. $CI_REGISTRY_IMAGE}"

case "${WITH_DEPS}" in
  1|true|TRUE|yes|YES)
    SUFFIX="-dep"
    ;;
  *)
    SUFFIX=""
    ;;
esac

printf '%s/%s%s:%s\n' "${REGISTRY_IMAGE}" "${IMAGE_FAMILY}" "${SUFFIX}" "${VERSION}"