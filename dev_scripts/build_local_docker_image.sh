#!/bin/sh
# Small helper script to build the base-python-dep image with the Tool API of this checkout,
# e.g. to test Tool API changes with a Tool in the testing bundle (see the FL-Net-Sandbox README).
set -eu
cd "$(dirname "$0")/.."

# The testing bundle always pulls new images on startup but ignores this tag,
# so keep the tag if you wanna use it in the testing bundle
TAG="${1:-testingtag}"

# Only the wheel is sent to docker as build context
CONTEXT="$(mktemp -d)"
trap 'rm -rf "$CONTEXT" build ./*.egg-info' EXIT
python3 -m pip wheel --no-deps -w "$CONTEXT" .
docker build -t "base-python-dep:$TAG" -f docker/Dockerfile.local "$CONTEXT"
