# vela-ci runner image

The image behind the `vela-ci` ARC scale set on vela's k3s (`runs-on: vela-ci`, runner group
`vela-k3s`). It exists for one job: vega-agent's `CI test`. Every job gets a fresh pod.

| File | Holds |
|---|---|
| `Dockerfile` | The Playwright image `ci.yml` pins (v1.59.0-noble, by digest) plus the Actions runner agent copied from the pinned stock runner image, a `runner` user (uid 1001) and a PATH-first venv. |
| `values.yaml` | The scale set's Helm values. `deploy.sh` fills in the image and the memory limit. |
| `deploy.sh` | Build, import into k3s's containerd, `helm upgrade --install vela-ci`. Never touches `vela-linux`. |

## Why a second scale set

`vela-linux` serves other repositories and has no browser. `CI test` runs inside the Playwright
image on a hosted VM (`container:`), and an ARC pod has no container mode: Docker-in-Docker needs
a privileged pod, and the Kubernetes container hooks cannot honour `--shm-size`. So the pod itself
is that image with the runner agent on top: same OS, Python 3.12 and `/ms-playwright` Chromium as
the job it replaces, which keeps the skip budget measured for it valid.

## What differs from a hosted `container:` job, and what covers it

| Hosted container | This pod | Covered by |
|---|---|---|
| runs as root; `pip install` goes to the system site, visible to `python -I` subprocesses | runs as uid 1001; user-site installs are invisible to `-I` | `/opt/venv` first on `PATH` (3 launcher tests failed with `ModuleNotFoundError: uvicorn` without it) |
| `--shm-size=1g` | pod `/dev/shm` is 64 MB | memory-backed `emptyDir` mounted at `/dev/shm` |
| 2 real cores, so `pytest -n auto` = 2 | a CPU limit is a cgroup quota; `os.cpu_count()` is the host's 16 | `PYTEST_XDIST_AUTO_NUM_WORKERS=2` in the pod env (measured: `cpu_count=16` inside `--cpus=2`) |
| `--pids-limit=512` | k3s default | none needed so far (peak 240 pids) |

## Sizing

vela is also a workstation (16 cores, ~14 GB free when measured on 2026-10-19), so the pod is sized
from a measurement, not from `vela-linux`'s 8 Gi.

Full vega-agent suite in this image under `--cpus=2 --memory=8g --shm-size=1g`, 2 xdist workers:
9,715 passed / 66 skipped in 358 s; **peak memory 1.6 GiB**, peak CPU 215 %, peak 240 pids.
Limit 4 Gi (2.5x the peak; the memory-backed `/dev/shm` counts against it), request 2 Gi,
`maxRunners: 2`. Worst case 8 Gi and 4 CPU for the whole set.

## Updating

```bash
MEMORY_LIMIT=4Gi ./deploy.sh 20261019     # tag = build date
```

Pods that are already running keep the image they started with. When `ci.yml` moves its Playwright
pin, move the `FROM` digest here in the same change, or the pod and the job it replaced drift apart.
