"""The packaged deployment (M8): images, compose services, proxy, persistence.

These tests build and start the real Docker Compose stack, so they run only when asked:

    NIFTY_DOCKER_TESTS=1 uv run pytest tests/test_docker.py

CI runs them in their own job. Each stack is a separate compose project on its own port,
with temporary folders for data, runs and studies, so a stack you are using is not touched.

The synthetic stack uses the hand-built week from test_engine.py and runs everywhere. The
real-data stack (also marked realdata) mounts your local data/ and studies/ and is skipped
without them.

Host vs container: a launch inside the container is compared with the same launch run on
this computer, in-process, from a folder laid out like the container's /app (data/ and
runs/ relative to the working directory, the same reference/). Every file of both run
folders must be byte-identical once the run id is replaced, including config.json and
manifest.json (the host run records the same git state the image was built with).
"""

import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nifty_backtest.api.app import create_app
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.engine.runs import git_output
from nifty_backtest.marketdata.config import DataConfig
from tests.helpers import REPO_DATA, write_index, write_processed
from tests.test_engine import MON, THU, TUE, WED, week

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "reference"

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("NIFTY_DOCKER_TESTS") != "1",
        reason="Docker tests run only with NIFTY_DOCKER_TESTS=1 (they build and start containers)",
    ),
]

# The synthetic week: one trade, entered Mon 4 Aug 2025, settled Thu 7 Aug 2025.
SYNTHETIC_LAUNCH = {"start": MON.isoformat(), "end": THU.isoformat()}
# The real data up to the end of the M7 validation period, so the run never depends on how
# recently `nifty-backtest download` was run.
REAL_LAUNCH = {"end": "2026-10-16"}
# nginx's mime.types has labelled .js both ways over the years; either is correct.
JAVASCRIPT = ("application/javascript", "text/javascript")


def _host_git() -> dict[str, str]:
    """The code version to bake into the images: the same state a host run records."""
    # -C: tests may have moved into a temporary folder (monkeypatch.chdir) by the time this runs.
    commit = git_output("-C", str(REPO), "rev-parse", "HEAD")
    status = git_output("-C", str(REPO), "status", "--porcelain")
    assert commit is not None, "the Docker tests need a git checkout"
    assert status is not None
    return {"GIT_COMMIT": commit, "GIT_DIRTY": "true" if status else "false"}


@dataclass
class Stack:
    """One running compose project and the host folders mounted into it."""

    project: str
    port: int
    data: Path
    runs: Path
    studies: Path

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            **_host_git(),
            "NIFTY_WEB_PORT": str(self.port),
            "NIFTY_DATA_DIR": str(self.data),
            "NIFTY_RUNS_DIR": str(self.runs),
            "NIFTY_STUDIES_DIR": str(self.studies),
            "NIFTY_UID": str(os.getuid()),
            "NIFTY_GID": str(os.getgid()),
        }

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = ["docker", "compose", "-f", str(REPO / "compose.yaml"), "-p", self.project]
        return subprocess.run(
            [*command, *args],
            env=self.env(),
            capture_output=True,
            text=True,
            check=check,
            timeout=900,
        )

    def up(self) -> None:
        done = self.compose("up", "-d", "--build", "--wait", check=False)
        if done.returncode != 0:
            logs = self.compose("logs", check=False).stdout
            self.compose("down", check=False)
            pytest.fail(f"compose up failed:\n{done.stderr}\n{logs}")

    def client(self) -> httpx.Client:
        # As long as nginx waits for a launch (proxy_read_timeout in frontend/nginx.conf).
        return httpx.Client(base_url=f"http://127.0.0.1:{self.port}", timeout=900)

    def image(self, service: str) -> str:
        return f"{self.project}-{service}"


@contextmanager
def _started(project: str, port: int, data: Path, runs: Path, studies: Path) -> Iterator[Stack]:
    stack = Stack(project, port, data, runs, studies)
    stack.up()
    try:
        yield stack
    finally:
        stack.compose("down", "--remove-orphans", check=False)


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    root = tmp_path_factory.mktemp("stack")
    data = DataConfig(data_dir=root / "data", start=MON, end=THU)
    write_processed(data, week())
    write_index(data, {MON: 25020.0, TUE: 25050.0, WED: 25100.0, THU: 24900.0})
    (root / "runs").mkdir()
    (root / "studies").mkdir()
    folders = (root / "data", root / "runs", root / "studies")
    with _started("nifty-backtest-test", 18080, *folders) as running:
        yield running


def _json(text: str) -> Any:
    return json.loads(text)


def _ps(stack: Stack) -> list[dict[str, Any]]:
    out = stack.compose("ps", "--format", "json").stdout.strip()
    # Compose prints one JSON object per line (older versions: one JSON list).
    return _json(out) if out.startswith("[") else [_json(line) for line in out.splitlines()]


# --- Configuration -------------------------------------------------------------------------


def test_only_the_dashboard_is_published_and_only_on_localhost(stack: Stack) -> None:
    config = _json(stack.compose("config", "--format", "json").stdout)
    services = config["services"]
    assert "ports" not in services["api"]  # the API is reachable only through nginx
    [web_port] = services["web"]["ports"]
    assert (web_port["host_ip"], web_port["published"], web_port["target"]) == (
        "127.0.0.1",
        str(stack.port),
        8080,
    )
    for name in ("api", "web"):
        service = services[name]
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert service["security_opt"] == ["no-new-privileges:true"], name
    mounts = {m["target"]: m for m in services["api"]["volumes"]}
    assert mounts["/app/data/processed"]["read_only"] is True
    assert mounts["/app/studies"]["read_only"] is True
    assert not mounts["/app/runs"].get("read_only", False)


def test_both_services_are_healthy(stack: Stack) -> None:
    states = {c["Service"]: (c["State"], c["Health"]) for c in _ps(stack)}
    assert states == {"api": ("running", "healthy"), "web": ("running", "healthy")}


def test_no_container_runs_as_root(stack: Stack) -> None:
    api = stack.compose("exec", "-T", "api", "id", "-u").stdout.strip()
    web = stack.compose("exec", "-T", "web", "id", "-u").stdout.strip()
    assert api == str(os.getuid())  # NIFTY_UID: your own user, so run folders belong to you
    assert web == "101"  # the unprivileged nginx image's own user
    assert "0" not in (api, web)


def test_images_contain_no_data_runs_studies_or_secrets(stack: Stack) -> None:
    def inside(image: str, script: str) -> str:
        # As root, only for this throwaway inspection container, so find can read every folder.
        return subprocess.run(
            ["docker", "run", "--rm", "--user", "0", "--entrypoint", "sh", image, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    assert inside(stack.image("api"), "ls -A /app").split() == [".venv", "reference"]
    assert sorted(inside(stack.image("api"), "ls /app/reference").split()) == sorted(
        p.name for p in REFERENCE.iterdir()
    )
    assert sorted(inside(stack.image("web"), "ls -A /usr/share/nginx/dashboard").split()) == [
        "assets",
        "index.html",
    ]
    # Nothing that should only ever live on this computer, anywhere in either image. pyarrow
    # ships a few tiny sample .parquet files with its own tests; those are skipped.
    search = (
        "find / -xdev -path '*/site-packages/pyarrow/tests' -prune -o \\( -name .env "
        "-o -name .git -o -name '*.parquet' -o -name 'manifest.json' -o -name 'study.json' \\) "
        "-print"
    )
    for service in ("api", "web"):
        assert inside(stack.image(service), search).split() == [], service


def test_only_the_runs_folder_is_writable(stack: Stack) -> None:
    def can_write(path: str) -> bool:
        done = stack.compose("exec", "-T", "api", "touch", path, check=False)
        return done.returncode == 0

    assert not can_write("/app/probe")  # read-only root filesystem
    assert not can_write("/app/data/processed/probe")  # read-only mount
    assert not can_write("/app/studies/probe")  # read-only mount
    assert can_write("/app/runs/probe")
    (stack.runs / "probe").unlink()  # written as you: removable from this computer


# --- Delivery and connectivity through nginx --------------------------------------------------


def test_the_dashboard_and_its_assets_are_served(stack: Stack) -> None:
    with stack.client() as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert page.headers["cache-control"] == "no-cache"
        assert page.headers["x-content-type-options"] == "nosniff"
        assert '<div id="root"></div>' in page.text
        assets = [part.split('"')[0] for part in page.text.split('="/assets/')[1:]]
        kinds = {name.rsplit(".", 1)[1] for name in assets}
        assert kinds == {"js", "css"}
        for name in assets:
            asset = client.get(f"/assets/{name}")
            assert asset.status_code == 200, name
            expected = ("text/css",) if name.endswith(".css") else JAVASCRIPT
            assert asset.headers["content-type"].startswith(expected), name
            assert "max-age=31536000" in asset.headers["cache-control"], name
        assert client.get("/assets/missing.js").status_code == 404


def test_the_api_and_its_documentation_are_reachable_through_the_proxy(stack: Stack) -> None:
    with stack.client() as client:
        assert client.get("/api/health").json()["status"] == "ok"
        # The same schema the dashboard's TypeScript types are generated from.
        committed = json.loads((REPO / "frontend/src/api/openapi.json").read_text())
        assert client.get("/openapi.json").json() == committed
        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "swagger" in docs.text.lower()
        # A 404 in the API's own JSON shape proves the request reached FastAPI, not nginx.
        missing = client.get("/api/runs/20000101-000000-none")
        assert (missing.status_code, missing.json()["error"]) == (404, "run_not_found")
        assert client.get("/api/studies").json() == []


# --- Launch, host comparison and persistence -------------------------------------------------


def _host_run(
    workdir: Path, runs: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, str]
) -> Path:
    """The same launch, in-process on this computer, from `workdir` laid out like /app. The
    runs folder is not recorded in the run, so it can be anywhere. A `workdir` outside the git
    checkout records the commit baked into the images (GIT_COMMIT / GIT_DIRTY), as the
    container does, so every saved file, manifest included, can be compared byte for byte."""
    for name, value in _host_git().items():  # read before leaving the checkout
        monkeypatch.setenv(name.replace("GIT_", "NIFTY_GIT_"), value)
    monkeypatch.chdir(workdir)
    with TestClient(create_app(ApiSettings(runs_dir=runs))) as client:
        response = client.post("/api/runs", json=body)
    assert response.status_code == 201, response.text
    return runs / str(response.json()["run_id"])


# The backtest itself: every trade, daily mark and equity value. These must be identical.
EXACT_FILES = {
    "config.json",
    "manifest.json",
    "trades.csv",
    "marks.csv",
    "equity.csv",
    "skipped.csv",
}
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _same_number(x: float, y: float) -> bool:
    # Equal to 12 significant digits. Two values that are both rounding noise around zero
    # (below a millionth, e.g. a reconciliation mismatch of 6e-11 Rs vs 1.2e-10 Rs) have no
    # significant digits to compare and count as equal.
    return math.isclose(x, y, rel_tol=1e-12) or (abs(x) < 1e-6 and abs(y) < 1e-6)


def _same_to_12_digits(ours: str, theirs: str) -> bool:
    """The same text, with every number the same to 12 significant digits."""
    if NUMBER.split(ours) != NUMBER.split(theirs):
        return False
    pairs = zip(NUMBER.findall(ours), NUMBER.findall(theirs), strict=True)
    return all(_same_number(float(x), float(y)) for x, y in pairs)


def _assert_same_run(container: Path, host: Path) -> None:
    """Statistics derived from the equity series (Sharpe, drawdowns, per-year figures) can
    differ in the last one or two of their 17 printed digits: numpy on Linux and on macOS
    adds long columns in a different order, and floating-point addition is not associative.
    Measured for M8 on the five-year run: at most 3.4e-13 relative. Those files are compared to
    12 significant digits, as the dashboard fixtures are (M6); everything else byte for byte."""
    names = sorted(p.name for p in container.iterdir())
    assert names == sorted(p.name for p in host.iterdir())
    assert EXACT_FILES.issubset(names)
    for name in names:
        ours = (container / name).read_text().replace(container.name, "RUN")
        theirs = (host / name).read_text().replace(host.name, "RUN")
        if name in EXACT_FILES:
            assert ours == theirs, f"{name} differs between the container and the host"
        else:
            assert _same_to_12_digits(ours, theirs), f"{name} differs beyond 12 digits"


def test_a_launched_run_matches_the_host_and_survives_a_restart(
    stack: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with stack.client() as client:
        response = client.post("/api/runs", json=SYNTHETIC_LAUNCH)
        assert response.status_code == 201, response.text
        run_id = response.json()["run_id"]
        before = {p: client.get(f"/api/runs/{run_id}{p}").json() for p in ("", "/trades")}
    folder = stack.runs / run_id
    assert (folder / "trades.csv").is_file()  # written to this computer, not the container
    manifest = json.loads((folder / "manifest.json").read_text())
    git = _host_git()
    assert manifest["git"] == {
        "commit": git["GIT_COMMIT"],
        "uncommitted_changes": git["GIT_DIRTY"] == "true",
    }

    workdir = tmp_path / "app"
    (workdir / "data").mkdir(parents=True)
    shutil.copytree(stack.data / "processed", workdir / "data" / "processed")
    (workdir / "reference").symlink_to(REFERENCE)
    _assert_same_run(folder, _host_run(workdir, tmp_path / "runs", monkeypatch, SYNTHETIC_LAUNCH))

    # Remove the containers entirely, start new ones: the run is still there, unchanged.
    stack.compose("down")
    stack.up()
    with stack.client() as client:
        after = {p: client.get(f"/api/runs/{run_id}{p}").json() for p in ("", "/trades")}
    assert after == before
    # Restarting only the API (which can change its address) keeps the proxy working.
    stack.compose("restart", "api")
    stack.compose("up", "-d", "--wait")
    with stack.client() as client:
        assert client.get(f"/api/runs/{run_id}").json() == before[""]


# --- Real data (local only) -------------------------------------------------------------------


@pytest.mark.realdata
def test_real_data_launch_matches_the_host_and_studies_are_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    studies = REPO / "studies"
    if not any((REPO_DATA / "processed" / "options").glob("*/*.parquet")) or not studies.is_dir():
        pytest.skip("needs the local data/processed and studies/ folders")
    (tmp_path / "runs").mkdir()
    project = "nifty-backtest-realdata"
    with (
        _started(project, 18081, REPO_DATA, tmp_path / "runs", studies) as stack,
        stack.client() as client,
    ):
        response = client.post("/api/runs", json=REAL_LAUNCH)
        assert response.status_code == 201, response.text
        container_run = stack.runs / response.json()["run_id"]
        ids = [s["study_id"] for s in client.get("/api/studies").json()]
        served_studies = {i: client.get(f"/api/studies/{i}").json() for i in ids}

    # The repository root is laid out like /app: data/ and reference/ relative to it.
    host_run = _host_run(REPO, tmp_path / "host-runs", monkeypatch, REAL_LAUNCH)
    _assert_same_run(container_run, host_run)
    assert sorted(served_studies) == sorted(p.name for p in studies.iterdir() if p.is_dir())
    with TestClient(create_app(ApiSettings(studies_dir=studies))) as client:
        for study_id, study in served_studies.items():
            assert client.get(f"/api/studies/{study_id}").json() == study
