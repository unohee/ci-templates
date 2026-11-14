# The ephemeral ARC runner for the `vela-rust-ci` scale set (k3s on vela).
#
# Replaces the two systemd runners rtx-rust-ci-1/2 (label `rust-ci`, account gha-rust).
# The Rust workflows (de-leak-rt, patina, intrect-plugin) expect what those hosts provided:
#   - CARGO_HOME/bin with cargo, rustc, rustup shims and a default toolchain;
#   - the X11 / Wayland / XCB / GL / glib dev packages their prerequisite step checks;
#   - a software Vulkan/GL stack (mesa lavapipe, xvfb): de-leak-rt's egui snapshot tests render
#     headless and failed 25 of 25 without it on the first run (2026-11-08);
#   - RUST_CI_TARGET_ROOT, a persistent directory for cargo target dirs (hostPath on NVMe,
#     see values.yaml), because a cold release build is ~17 min.
# Versions match hosts/vela/rust-ci/README.md in the self-hosted-runner notes (Rust 1.98.1,
# cargo-audit 0.22.2).
FROM ghcr.io/actions/actions-runner@sha256:4ffadc0002b2581327e06101fc8c06cd189232baf79fe561fac9caeb76f5e807

ARG RUST_VERSION=1.98.1

USER root

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential pkg-config git curl ca-certificates jq make rsync file zstd xz-utils unzip \
      libx11-dev libx11-xcb-dev libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev \
      libxcb1-dev libxcb-render0-dev libxcb-shape0-dev libxcb-xfixes0-dev libxcb-icccm4-dev \
      libgl-dev libglib2.0-dev libasound2-dev libssl-dev libfontconfig-dev \
      mesa-vulkan-drivers libvulkan1 libgl1-mesa-dri libegl1 libegl-dev xvfb \
      python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

ENV RUSTUP_HOME=/opt/rust/rustup \
    CARGO_HOME=/opt/rust/cargo \
    PATH=/opt/rust/cargo/bin:${PATH} \
    RUST_CI_TARGET_ROOT=/cache/cargo-target \
    RUNNER_TOOL_CACHE=/opt/hostedtoolcache \
    AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache

# Owned by the job user from the start: a later chown -R would duplicate the tree in a layer.
RUN install -d -o runner -g runner /opt/rust /opt/hostedtoolcache
USER runner

RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain ${RUST_VERSION} \
      --component clippy --component rustfmt --no-modify-path

COPY --chown=runner:runner --chmod=0755 cargo-audit /opt/rust/cargo/bin/cargo-audit
