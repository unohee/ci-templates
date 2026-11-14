#!/usr/bin/env bash
# Build the vela-rust-ci runner image, hand it to k3s, and install or upgrade the scale set.
# Run on vela as a user with passwordless sudo and docker.   ./deploy.sh 20261108
set -euo pipefail
tag="${1:?usage: deploy.sh <tag>}"
here="$(cd "$(dirname "$0")" && pwd)"
image="localhost/vela-rust-ci-runner:${tag}"
cache=/media/unohee/nvme1tb/gha-rust-arc/cargo-target

# Persistent target root for the pods (uid 1001 = runner). Left empty on first run.
sudo install -d -o 1001 -g 1001 "$cache"

docker build -t "$image" "$here"
docker save "$image" | sudo k3s ctr -n k8s.io images import -
# Pin it: an unpinned image with no running pod gets GC-ed (ImagePullBackOff, see vela-ci).
sudo k3s ctr -n k8s.io images label "$image" io.cri-containerd.pinned=pinned >/dev/null

values="$(mktemp)"
trap "rm -f \"$values\"" EXIT
sed -e "s#IMAGE_PLACEHOLDER#${image}#" "$here/values.yaml" > "$values"
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install vela-rust-ci \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f "$values"
