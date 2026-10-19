#!/usr/bin/env bash
# Build the vela-ci runner image, hand it to k3s, and install or upgrade the scale set.
# Run on vela (the k3s host) as a user with passwordless sudo.
#
#   ./deploy.sh 20261019
#   MEMORY_LIMIT=6Gi ./deploy.sh 20261019
#
# Runner pods that are already running keep their old image; new jobs get the new one.
# `helm upgrade --install` creates the release on the first run, so this is also the
# first-time installer. It never touches the `vela-linux` release.
set -euo pipefail
tag="${1:?usage: deploy.sh <tag>}"
memory="${MEMORY_LIMIT:?set MEMORY_LIMIT, the measured pod ceiling (see README Sizing)}"
here="$(cd "$(dirname "$0")" && pwd)"
image="localhost/vela-ci-runner:${tag}"

docker build -t "$image" "$here"
docker save "$image" | sudo k3s ctr images import -

values="$(mktemp)"
trap 'rm -f "$values"' EXIT
sed -e "s#IMAGE_PLACEHOLDER#${image}#" -e "s#MEMORY_LIMIT_PLACEHOLDER#${memory}#" \
  "$here/values.yaml" > "$values"
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install vela-ci \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f "$values"
