FROM mcr.microsoft.com/devcontainers/python:3.13-bookworm

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
