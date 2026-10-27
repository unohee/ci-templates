# The ephemeral ARC runner for the `vela-linux` scale set (k3s on vela).
#
# The stock actions-runner image is a bare Ubuntu: no `file`, `gh`, `ss`, `lsof`,
# `zsh` or `fish`, and no sudo inside the pod (allowPrivilegeEscalation: false),
# so a job cannot install them itself. Measured on vega-cli PR #15 (2026-10-16):
# the release's Mach-O check and publish step, `vega daemon start` (it waits on
# `ss`) and the zsh/fish completion tests all depended on them.
#
# Every pod also started with an empty tool cache, so setup-python and
# setup-node downloaded their runtimes on every job (7 s and 5 s). The versions
# the org's workflows ask for are installed into the tool cache here; anything
# else is still downloaded as before, so a stale image is slower, never wrong.

# Pinned by digest: `latest` is what the scale set ran before, and a moving base
# would change every job's environment without a commit.
FROM ghcr.io/actions/actions-runner@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807

ARG PYTHON_VERSION=3.12.15
ARG PYTHON_URL=https://github.com/actions/python-versions/releases/download/3.12.15-36805895057/python-3.12.15-linux-24.04-x64.tar.gz
ARG NODE_VERSION=22.23.3
ARG GH_VERSION=2.102.0

USER root

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      file iproute2 lsof zsh fish xz-utils zstd ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Headers that jobs ask for in `pkg-config` terms and cannot install themselves: a
# pod has no sudo. Two callers drive this list.
#
# * Rust audio plug-ins and apps — baseview/nih_plug_egui link X11, xcb, xkbcommon
#   and GL; cpal/midir link ALSA through pkg-config.
# * de-artifact's `build (linux)` — probes `pkg-config --exists x11 x11-xcb xcb
#   xkbcommon wayland-client egl glesv2` and runs `sudo apt-get` only when the probe
#   fails, so every module it names has to resolve here.
#
# Measured on 2026-10-27 in localhost/vela-linux-runner:20261026d, before this layer:
# x11, x11-xcb, xcb and xkbcommon resolved, `wayland-client`, `egl` and `glesv2` did
# not — which is the `build (linux)` list failing on an ARC pod. The list below is
# that job's own apt-get list, verbatim, plus the GUI/ALSA set.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      pkg-config libasound2-dev \
      libx11-dev libx11-xcb-dev libxcb1-dev libxcb-icccm4-dev \
      libxcb-util-dev libxcb-dri2-0-dev libxkbcommon-dev libxkbcommon-x11-dev \
      libxcursor-dev libxrandr-dev libwayland-dev \
      libgl-dev libglu1-mesa-dev libegl1-mesa-dev libgles2-mesa-dev \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
      | tar -xz -C /tmp \
 && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh \
 && rm -rf "/tmp/gh_${GH_VERSION}_linux_amd64"

# The runner reads its tool cache from here instead of _work/_tool, so the
# pre-installed runtimes survive the per-job work directory.
ENV RUNNER_TOOL_CACHE=/opt/hostedtoolcache \
    AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache

# Owned by the job user before anything is written, and filled as that user:
# a `chown -R` afterwards would copy the whole tree into another layer.
RUN install -d -o runner -g runner /opt/hostedtoolcache
USER runner

# actions/python-versions' own installer lays the tree out the way setup-python
# looks for it (Python/<version>/x64 plus the .complete marker).
RUN mkdir -p /tmp/py \
 && curl -fsSL "$PYTHON_URL" | tar -xz -C /tmp/py \
 && cd /tmp/py && bash ./setup.sh \
 && rm -rf /tmp/py

RUN dir="/opt/hostedtoolcache/node/${NODE_VERSION}/x64" \
 && mkdir -p "$dir" \
 && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
      | tar -xJ -C "$dir" --strip-components=1 \
 && touch "$dir.complete"

