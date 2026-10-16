#!/usr/bin/env bash
# Build the vela-linux runner image, hand it to k3s, and point the scale set at it.
# Run on vela (the k3s host) as a user with passwordless sudo.
#
#   ./deploy.sh 20261016
#
# Runner pods that are already running keep their old image; new jobs get the new one.
set -euo pipefail
tag="${1:?usage: deploy.sh <tag>}"
here="$(cd "$(dirname "$0")" && pwd)"
image="localhost/vela-linux-runner:${tag}"

docker build -t "$image" "$here"
docker save "$image" | sudo k3s ctr images import -

values="$(mktemp)"
trap 'rm -f "$values"' EXIT
sed "s#IMAGE_PLACEHOLDER#${image}#" "$here/values.yaml" > "$values"
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade vela-linux \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f "$values"
