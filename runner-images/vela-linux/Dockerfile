# The ephemeral ARC runner for the `vela-linux` scale set (k3s on vela). The
# `vela-legacy-labels` scale set runs the same image.
#
# Built on Ubuntu 26.04 so the runner's glibc matches vela's. vela was
# dist-upgraded to 26.04 on 2026-11-05 (kernel 7.0.0-42, glibc 2.43). From then on
# the stock actions-runner image (24.04, glibc 2.39) aborted Runner.Listener mid-job
# in about 1% of jobs, and in 3 of 42 pods during one 25-minute window. The runner
# log ends `Segmentation fault (core dumped)` / `Exiting with unknown error code:
# 139`, and the kernel logs a general protection fault in `.NET TP Worker` at
# libc.so.6[289a2], inside glibc 2.39's abort(). The systemd runners on the same
# host run the same runner tarball on the host's glibc 2.43 and have never crashed.
# GLIBC_TUNABLES=glibc.pthread.rseq=0 did not help.
#
# The stock image cannot simply be swapped: it is built on
# mcr.microsoft.com/dotnet/runtime-deps:8.0-noble, and MCR publishes no 8.0 tag for
# 26.04 (resolute; checked 2026-11-10). So the first half of this file rebuilds
# what the stock image provides
# (actions/runner v2.338.2 images/Dockerfile). Two parts are left out on purpose.
# The Docker CLI and buildx: the pods have no Docker daemon, and none of the
# Intrect-io workflows that target vela-linux calls docker (their image builds run
# on the `oci-build` runner; checked 2026-11-10). The git-core PPA: 26.04's own git is recent enough.
#
# Then come the additions. The stock image is a bare Ubuntu: no `file`, `gh`, `ss`,
# `lsof`, `zsh` or `fish`, and no sudo inside the pod
# (allowPrivilegeEscalation: false), so a job cannot install them itself. Measured
# on vega-cli PR #15 (2026-10-16): the release's Mach-O check and publish step,
# `vega daemon start` (it waits on `ss`) and the zsh/fish completion tests all
# needed them.
#
# Every pod also started with an empty tool cache, so setup-python and setup-node
# downloaded their runtimes on every job (7 s and 5 s). The versions the org's
# workflows ask for are installed into the tool cache here. Any other version is
# still downloaded as before, so a stale image is slower, never wrong.

# ubuntu:26.04 is pinned by digest: a moving base would change every job's
# environment without a commit.
ARG UBUNTU_IMAGE=ubuntu:26.04@sha256:6a06111c3b0a8600feadb270aec771dc239bf407b25625f93f44ab00e11f4d3c

# --- fetch: runner and container hooks, checksum-verified -------------------------
FROM ${UBUNTU_IMAGE} AS fetch

# The runner checksum is the one the v2.338.2 release notes publish. The 0.8.1
# hooks checksum is GitHub's asset digest. 0.7.0 has no published digest, so its
# checksum was taken from the release asset on 2026-11-10.
ARG RUNNER_VERSION=2.338.2
ARG RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40
ARG HOOKS_VERSION=0.7.0
ARG HOOKS_SHA256=a66047498bada808a1d611b006db2ab634efaeb668af9d9a2fb8a9c6e1936f45
ARG HOOKS_NOVOLUME_VERSION=0.8.1
ARG HOOKS_NOVOLUME_SHA256=2c3c4526f8a8d517373a2a0daa6122d7887bdc465c54945c6d716db87d9d9b4f

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /actions-runner
RUN curl -fsSL -o runner.tar.gz \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
 && echo "${RUNNER_SHA256}  runner.tar.gz" | sha256sum -c - \
 && tar xzf runner.tar.gz \
 && rm runner.tar.gz

# The same two hook trees the stock image ships. ARC only uses them in
# containerMode kubernetes, which this scale set does not set; they are here so
# that switching modes does not also need an image change.
RUN curl -fsSL -o hooks.zip \
      "https://github.com/actions/runner-container-hooks/releases/download/v${HOOKS_VERSION}/actions-runner-hooks-k8s-${HOOKS_VERSION}.zip" \
 && echo "${HOOKS_SHA256}  hooks.zip" | sha256sum -c - \
 && unzip -q hooks.zip -d ./k8s \
 && rm hooks.zip \
 && curl -fsSL -o hooks.zip \
      "https://github.com/actions/runner-container-hooks/releases/download/v${HOOKS_NOVOLUME_VERSION}/actions-runner-hooks-k8s-${HOOKS_NOVOLUME_VERSION}.zip" \
 && echo "${HOOKS_NOVOLUME_SHA256}  hooks.zip" | sha256sum -c - \
 && unzip -q hooks.zip -d ./k8s-novolume \
 && rm hooks.zip

# --- runner image ---------------------------------------------------------------
FROM ${UBUNTU_IMAGE}

ARG PYTHON_VERSION=3.12.15
ARG PYTHON_URL=https://github.com/actions/python-versions/releases/download/3.12.15-36805895057/python-3.12.15-linux-26.04-x64.tar.gz
ARG NODE_VERSION=22.23.3
ARG GH_VERSION=2.102.0

# The stock image's environment. DOTNET_RUNNING_IN_CONTAINER comes from its
# dotnet/runtime-deps base.
ENV DEBIAN_FRONTEND=noninteractive \
    RUNNER_MANUALLY_TRAP_SIG=1 \
    ACTIONS_RUNNER_PRINT_LOG_TO_STDOUT=1 \
    DOTNET_RUNNING_IN_CONTAINER=true \
    ImageOS=ubuntu26

# The runner is a self-contained .NET app. Its native dependencies are the list
# bin/installdependencies.sh installs on Ubuntu (krb5, zlib, lttng-ust, OpenSSL,
# ICU), resolved to their 26.04 names, plus the rest of dotnet/runtime-deps
# (ca-certificates, libgcc-s1, libstdc++6, tzdata, tzdata-legacy; the last one
# keeps the US/* and EST5EDT-style zone names that 26.04 split out of tzdata).
# After those come the
# utilities the stock image adds. The stock image installs git with its
# recommends, which is where its less, openssh-client and patch came from; they
# are named here so that --no-install-recommends does not drop them.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates libgcc-s1 libstdc++6 tzdata tzdata-legacy \
      libkrb5-3 zlib1g liblttng-ust1t64 libssl3t64 libicu78 \
      sudo lsb-release curl jq unzip git less openssh-client patch \
 && rm -rf /var/lib/apt/lists/*

# Same user and groups as the stock image: uid 1001 in docker (gid 123), with a
# passwordless sudo that cannot actually elevate in a pod without privilege
# escalation, but keeps `sudo -n` failing the same way it did before. The 26.04
# base has no `adduser`; this useradd line gives what the stock image's
# `adduser --disabled-password` gave (home from /etc/skel, bash, group `users`).
RUN useradd --create-home --uid 1001 --shell /bin/bash --groups users runner \
 && groupadd docker --gid 123 \
 && usermod -aG sudo runner \
 && usermod -aG docker runner \
 && echo "%sudo   ALL=(ALL:ALL) NOPASSWD:ALL" > /etc/sudoers \
 && echo "Defaults env_keep += \"DEBIAN_FRONTEND\"" >> /etc/sudoers \
 && chmod 777 /home/runner

WORKDIR /home/runner
# The scale set starts /home/runner/run.sh (values.yaml `command`).
COPY --chown=runner:docker --from=fetch /actions-runner .

# The second half of this list was in the image vela ran (20261027) but never
# reached main: it came from the open feat/vela-linux-gui-audio-libs branch
# (cf76637, 02e901f, 8750ab7). It is kept so that moving to 26.04 does not also
# take tools away. build-essential is the C toolchain: cgo for vega-plugins'
# go-sqlite3 bridge tests, and the `cc` that rustc links with. python3-venv was
# python3.12-venv on 24.04 (STONKS lint venv); on 26.04 the system Python is 3.14.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      file iproute2 lsof zsh fish xz-utils zstd \
      make rsync libatomic1 build-essential python3-venv \
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
# that job's own apt-get list, verbatim, plus the GUI/ALSA set. Every name still
# exists on 26.04 (checked 2026-11-10).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
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
#
# The 24.04 image had a system python3.12, and STONKS' lint job calls
# `python3.12 -m venv` by name. 26.04's system Python is 3.14, so the name points
# at the tool-cache 3.12 below. The link dangles until that layer fills it.
RUN install -d -o runner -g runner /opt/hostedtoolcache \
 && ln -s "/opt/hostedtoolcache/Python/${PYTHON_VERSION}/x64/bin/python${PYTHON_VERSION%.*}" \
      "/usr/local/bin/python${PYTHON_VERSION%.*}"
USER runner

# actions/python-versions' own installer lays the tree out the way setup-python
# looks for it (Python/<version>/x64 plus the .complete marker). The 26.04 build,
# because setup-python picks builds by the OS version it runs on; a 24.04 build
# here would be a cache entry built for a different system than the one that
# downloads the next version.
RUN mkdir -p /tmp/py \
 && curl -fsSL "$PYTHON_URL" | tar -xz -C /tmp/py \
 && cd /tmp/py && bash ./setup.sh \
 && rm -rf /tmp/py

RUN dir="/opt/hostedtoolcache/node/${NODE_VERSION}/x64" \
 && mkdir -p "$dir" \
 && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
      | tar -xJ -C "$dir" --strip-components=1 \
 && touch "$dir.complete"
