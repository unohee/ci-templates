#!/usr/bin/env bash
# Install or upgrade the vela-platform scale set on vela's k3s.
# Run on vela (the k3s host) as a user with passwordless sudo.
#
#   ./deploy.sh 20261026 20261016   # <this image tag> <vela-linux base tag>
#
# Builds vela-platform-runner on top of the vela-linux image (../vela-linux, which must
# already be in the local Docker image store), imports it into k3s's containerd, and
# installs the scale set. The sidecar images (redis, postgres) are pulled by the kubelet.
# `helm upgrade --install` creates the release on the first run. It never touches the
# vela-linux or vela-ci releases.
set -euo pipefail
tag="${1:?usage: deploy.sh <tag> <vela-linux base tag>}"
base_tag="${2:?usage: deploy.sh <tag> <vela-linux base tag>}"
here="$(cd "$(dirname "$0")" && pwd)"
base="localhost/vela-linux-runner:${base_tag}"
image="localhost/vela-platform-runner:${tag}"

if ! docker image inspect "$base" >/dev/null 2>&1; then
  echo "missing $base in Docker; build it with ../vela-linux/deploy.sh ${base_tag} first" >&2
  exit 1
fi
docker build --build-arg "BASE=${base}" -t "$image" "$here"
docker save "$image" | sudo k3s ctr -n k8s.io images import -
# Pin it: the root disk runs above kubelet's image-gc-high-threshold, so an unpinned image
# with no running pod is garbage-collected and the next runner pod fails ImagePullBackOff
# (lost vela-ci and vela-platform images on 2026-10-25/26).
sudo k3s ctr -n k8s.io images label "$image" io.cri-containerd.pinned=pinned >/dev/null

values="$(mktemp)"
trap 'rm -f "$values"' EXIT
sed "s#IMAGE_PLACEHOLDER#${image}#" "$here/values.yaml" > "$values"
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install vela-platform \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f "$values"
