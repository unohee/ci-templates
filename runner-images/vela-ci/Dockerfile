# The ephemeral ARC runner for the `vela-ci` scale set (k3s on vela).
#
# vega-agent's `CI test` job runs inside a pinned Playwright image on a hosted VM
# (`container:` in its ci.yml). ARC pods here have no container mode: no Docker-in-
# Docker (it needs a privileged pod) and no Kubernetes container hooks (they cannot
# honour `--shm-size`). So the pod itself has to BE that image, with the Actions
# runner agent added on top. Same base OS, same Python 3.12, same /ms-playwright
# Chromium: the job's steps, and the skip budget measured for them, stay valid.
#
# Kept apart from the shared `vela-linux` image on purpose: that one serves other
# repositories and Chromium (~600 MB) would change their pods too.

# The runner agent is copied from the stock actions-runner image. Pinned by digest,
# the same one the `vela-linux` image uses, so both scale sets run one agent build.
FROM ghcr.io/actions/actions-runner@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807 AS runner

# The exact image vega-agent's ci.yml pins (v1.59.0-noble). When that pin moves, move
# this line with it, or the runner and the job it replaces drift apart.
FROM mcr.microsoft.com/playwright/python@sha256:d8d9811a0e7cfac967f0c2f55d12b739087ae4b0808577b794c2a29ed5124938

USER root

# The runner agent is a self-contained .NET program; these are the libraries its
# runtime-deps image carries and the Playwright image does not.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libicu74 tzdata ca-certificates curl python3.12-venv \
 && rm -rf /var/lib/apt/lists/*

# uid 1001 matches the stock runner image, so the scale set's securityContext and
# any file ownership assumptions carry over unchanged. The Playwright image already
# owns 1001 as `pwuser`, so rename it and move its home rather than adding a second
# account (`groupadd --gid 1001` fails: the id is taken).
RUN groupmod --new-name runner pwuser \
 && usermod --login runner --home /home/runner --move-home pwuser

COPY --from=runner --chown=1001:1001 /home/runner /home/runner

# Same variables the stock image sets for ARC, plus the tool cache location. The
# Playwright image already exports PLAYWRIGHT_BROWSERS_PATH=/ms-playwright, which is
# where ci.yml looks for the pinned Chromium.
ENV RUNNER_MANUALLY_TRAP_SIG=1 \
    ACTIONS_RUNNER_PRINT_LOG_TO_STDOUT=1 \
    ImageOS=ubuntu24 \
    RUNNER_TOOL_CACHE=/opt/hostedtoolcache \
    AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache \
    HOME=/home/runner

RUN install -d -o runner -g runner /opt/hostedtoolcache

# Hosted `container:` jobs run as root, so `pip install` lands in the system site and is
# visible to subprocesses started with `python -I` (isolated mode ignores the user site).
# A non-root pod would put it in ~/.local and those subprocesses would not find uvicorn
# (measured: 3 launcher tests failed with ModuleNotFoundError, 9,715 others passed). An
# environment that is on PATH from the start gives the job the same behaviour with no
# workflow change; --system-site-packages keeps what the Playwright image preinstalls.
RUN python -m venv --system-site-packages /opt/venv \
 && chown -R runner:runner /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

USER runner
WORKDIR /home/runner
