FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm@sha256:574cffd335538d1c1d8b3daf10fabd27c8783c55f3b9e6070cbd921ad2497877

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
