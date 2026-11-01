# The API image (M8): the nifty_backtest package with exactly the dependencies in uv.lock,
# plus the tracked reference/ files. Market data, runs and studies are NOT in the image; they
# are bind-mounted from this computer at run time (compose.yaml).
#
# Every base image is pinned by version AND sha256 digest, so a rebuild months from now
# starts from byte-identical layers. To upgrade, change both together.

# uv, the same version CI uses (.github/workflows/ci.yml). Only the build stage uses it.
FROM ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

# --- Build stage: install the locked dependencies and the package into /app/.venv ---------
# Python 3.12.15, the version in .python-version, on Debian 13 (trixie).
FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build
COPY --from=uv /uv /usr/local/bin/uv
# Compile .pyc files now (the runtime filesystem is read-only); copy files instead of
# hard-linking them from uv's cache; use the image's Python, never a downloaded one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /build
# Dependencies first, in their own layer: editing the code does not reinstall pandas.
# --locked fails if uv.lock disagrees with pyproject.toml; --no-dev leaves out pytest, mypy
# and ruff.
COPY pyproject.toml uv.lock .python-version README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
# --no-editable copies the package into the environment, so src/ is not needed at run time.
RUN uv sync --locked --no-dev --no-editable

# --- Runtime stage: Python, the environment and reference/, nothing else -------------------
FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY reference ./reference

# The commit this image was built from (see engine/runs.py, _baked_git_state). The image has
# no git, so runs launched in it record these values. Left empty, runs record commit "unknown"
# with uncommitted changes, never a clean state nobody checked.
ARG GIT_COMMIT=""
ARG GIT_DIRTY=""
LABEL org.opencontainers.image.title="nifty-backtest-api" \
      org.opencontainers.image.revision="${GIT_COMMIT}"
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    NIFTY_GIT_COMMIT=${GIT_COMMIT} \
    NIFTY_GIT_DIRTY=${GIT_DIRTY}

# Not root. compose.yaml can override the ids (NIFTY_UID/NIFTY_GID) so that run folders the
# container writes into the bind-mounted runs/ belong to you on Linux.
USER 1000:1000
EXPOSE 8000
# 0.0.0.0 inside the container's own network: compose.yaml publishes no port for this
# service, so only the dashboard's proxy can reach it. The CLI's "no authentication" warning
# is printed at start-up, and it is accurate.
CMD ["nifty-backtest", "serve", "--host", "0.0.0.0", "--port", "8000"]
