# vela-deartifact-serverless

ARC scale set with Docker-in-Docker for de-artifact's serverless image builds
(`release-serverless*.yml`, `runs-on: vela-deartifact-serverless`). Image: the stock
vela-linux runner image (`../vela-linux`); dockerd is the `docker:27.5-dind` sidecar.

Copied on 2026-11-15 (AGT-4910) from de-artifact's unmerged branch
`ci/k3s-linux-runners` (`ci/vela-runner/`, PR #248). The values equal the live release.

```bash
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install vela-deartifact-serverless \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f values.yaml
```

dockerd keeps its data root on a hostPath on the seagate disk, so `maxRunners` stays 1:
two dockerds must not share one data root.
