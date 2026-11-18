#!/usr/bin/env bash
# Build the vela-rust-ci runner image, hand it to k3s, and install or upgrade the scale set.
# Run on vela as a user with passwordless sudo and docker.   ./deploy.sh 20261118
#
# ./deploy.sh --check          report status only: active runner pods, live image, drift.
# FORCE=1 ./deploy.sh <tag>    upgrade even though runner pods are mid-job.
#
# Why the guard: `helm upgrade` recreates the EphemeralRunnerSet, and the controller deletes the
# runner pods with it. An in-flight job then dies with "The runner has received a shutdown
# signal" (exit 130) even though nothing about the job was wrong. On 2026-11-17 the xxd image
# upgrade at 10:17:11 KST killed two `release contracts (v030)` jobs that had been waiting on the
# shared cargo target lock since 10:09, and the red main check was read as a runner fault for a
# day. Upgrading while the queue is empty costs nothing; the pods start in ~1.3s.
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
scale_set=vela-rust-ci
namespace=arc-runners
here="$(cd "$(dirname "$0")" && pwd)"

as_root() { sudo env KUBECONFIG="$KUBECONFIG" "$@"; }

active_runners() {
  as_root kubectl get pods -n "$namespace" \
    -l "actions.github.com/scale-set-name=${scale_set}" \
    --field-selector=status.phase=Running \
    -o custom-columns='NAME:.metadata.name,START:.status.startTime' --no-headers 2>/dev/null || true
}

live_image() {
  as_root kubectl get autoscalingrunnerset "$scale_set" -n "$namespace" \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true
}

if [ "${1:-}" = "--check" ]; then
  echo "scale set : $scale_set / $namespace"
  echo "live image: $(live_image)"
  active="$(active_runners)"
  if [ -n "$active" ]; then
    echo "running runner pods (a job holds each; an upgrade now kills it):"
    echo "$active" | sed 's/^/  /'
  else
    echo "running runner pods: none (safe to upgrade)"
  fi
  exit 0
fi

tag="${1:?usage: deploy.sh <tag>  |  deploy.sh --check}"
image="localhost/vela-rust-ci-runner:${tag}"
cache=/media/unohee/nvme1tb/gha-rust-arc/cargo-target

active="$(active_runners)"
if [ -n "$active" ] && [ "${FORCE:-0}" != "1" ]; then
  cat >&2 <<EOF
refusing to upgrade: $scale_set has runner pods mid-job. The upgrade deletes them and their jobs
die with a shutdown signal. Wait for the queue to drain, then re-run. Pods now running:
$(echo "$active" | sed 's/^/  /')
Override only if the kill is intended: FORCE=1 $0 $tag
EOF
  exit 3
fi

# Persistent target root for the pods (uid 1001 = runner). Left empty on first run.
sudo install -d -o 1001 -g 1001 "$cache"

docker build -t "$image" "$here"
docker save "$image" | sudo k3s ctr -n k8s.io images import -
# Pin it: an unpinned image with no running pod gets GC-ed (ImagePullBackOff, see vela-ci).
sudo k3s ctr -n k8s.io images label "$image" io.cri-containerd.pinned=pinned >/dev/null

values="$(mktemp)"
trap "rm -f \"$values\"" EXIT
sed -e "s#IMAGE_PLACEHOLDER#${image}#" "$here/values.yaml" > "$values"
as_root helm upgrade --install "$scale_set" \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n "$namespace" -f "$values"
