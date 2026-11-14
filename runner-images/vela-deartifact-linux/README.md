# vela-deartifact-linux

ARC scale set for de-artifact's `build (linux)` job (`runs-on: vela-deartifact-linux`
in `ci-rust.yml`). It replaced the systemd runner `rtx-deartifact-linux`, which was
deregistered on 2026-11-15 (AGT-4906).

The image is the vela-linux image plus the native packages nih-plug (VST3/CLAP,
baseview X11/Wayland, wgpu) and openssl-sys need, and a rustup stable toolchain. Pods
run with no-new-privileges, so nothing can be apt-installed during a job.

These files were copied on 2026-11-15 (AGT-4910) from de-artifact's unmerged branch
`ci/k3s-linux-runners` (`ci/vela-runner/`, PR #248). The values equal the live release.
The live image `localhost/de-artifact-linux-runner:20261027` was built from that
Dockerfile; its layer history matches it. Despite the tag, it was built on 2026-11-09.

Rebuild and roll out on vela:

```bash
tag=$(date +%Y%m%d)
image=localhost/de-artifact-linux-runner:$tag
docker build -t "$image" .
docker save "$image" | sudo k3s ctr -n k8s.io images import -
sudo k3s ctr -n k8s.io images label "$image" io.cri-containerd.pinned=pinned
# bump `image:` in values.yaml, then
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install vela-deartifact-linux \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.15.0 -n arc-runners -f values.yaml
```

Keep `maxRunners` at 1: each release build writes a 10-20 GB target dir to the node disk.
