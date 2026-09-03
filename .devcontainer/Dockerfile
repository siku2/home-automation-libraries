FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:5ba8adb657d39077e35620747b4798f2b88204a0237c19601eefb9d49f512270

SHELL ["/bin/bash", "-c"]

RUN <<EOF
set -euo pipefail

PIPX_DEPS=(
    git-cliff
    typos
    uv
)

for dep in "${PIPX_DEPS[@]}"; do
    pipx install "$dep"
done
EOF
