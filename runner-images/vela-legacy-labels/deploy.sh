#!/usr/bin/env bash
# Deploy the `vela-legacy-labels` scale set against an image that already exists.
#
#   ./deploy.sh 20261027
#
# The tag names an image `runner-images/vela-linux/deploy.sh` built and imported
# into k3s's containerd — this scale set runs the same image, so there is nothing
# to build here and nothing to pull.
#
# Run on vela (the k3s host) as a user with passwordless sudo.
set -euo pipefail
tag="${1:?usage: deploy.sh <image-tag, e.g. 20261027>}"
here="$(cd "$(dirname "$0")" && pwd)"
image="localhost/vela-linux-runner:${tag}"

# Fail loudly instead of deploying a scale set whose pods cannot start: k3s cannot
# pull this reference, so a missing image is ImagePullBackOff on every job. The
# containerd name drops the `localhost/` prefix.
if ! sudo k3s ctr -n k8s.io images ls -q | grep -q "vela-linux-runner:${tag}"; then
  echo "image ${image} is not in k3s's containerd — run runner-images/vela-linux/deploy.sh ${tag} first" >&2
  exit 1
fi

values="$(mktemp)"
trap 'rm -f "$values"' EXIT
sed "s#IMAGE_PLACEHOLDER#${image}#" "$here/values.yaml" > "$values"
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install vela-legacy-labels \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f "$values"
