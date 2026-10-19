"""Downloader behaviour against a fake NSE server (httpx.MockTransport): no network needed."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date

import httpx

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import download_range, read_log
from nifty_backtest.marketdata.sources import Format, raw_path

ZIP_BYTES = b"PK\x03\x04 rest of a zip file"


def fake_nse(respond: Callable[[httpx.Request], httpx.Response]) -> tuple[httpx.Client, list[str]]:
    """A client whose requests go to `respond` instead of the internet; also records URLs."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return respond(request)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def no_sleep(_: float) -> None:
    pass


def one_day(cfg: DataConfig, day: date) -> DataConfig:
    return replace(cfg, start=day, end=day)


def test_saves_file_and_logs_ok(cfg: DataConfig) -> None:
    day = date(2023, 3, 1)  # legacy period: exactly one request
    client, seen = fake_nse(lambda r: httpx.Response(200, content=ZIP_BYTES))
    summary = download_range(one_day(cfg, day), client, today=date(2026, 1, 1), sleep=no_sleep)

    assert summary.downloaded == 1
    assert len(seen) == 1
    path = raw_path(cfg, Format.LEGACY, day)
    assert path.read_bytes() == ZIP_BYTES
    assert not list(path.parent.glob("*.part"))  # the temporary file was renamed away
    assert read_log(cfg)[(day, Format.LEGACY)]["status"] == "ok"


def test_404_is_logged_as_no_session(cfg: DataConfig) -> None:
    day = date(2023, 3, 4)  # a Saturday
    client, _ = fake_nse(lambda r: httpx.Response(404))
    summary = download_range(one_day(cfg, day), client, today=date(2026, 1, 1), sleep=no_sleep)

    assert summary.not_found == 1
    assert not raw_path(cfg, Format.LEGACY, day).exists()
    assert read_log(cfg)[(day, Format.LEGACY)]["status"] == "not_found"


def test_html_instead_of_zip_is_an_error_not_a_file(cfg: DataConfig) -> None:
    day = date(2023, 3, 1)
    client, _ = fake_nse(lambda r: httpx.Response(200, content=b"<html>Access denied</html>"))
    summary = download_range(one_day(cfg, day), client, today=date(2026, 1, 1), sleep=no_sleep)

    assert summary.errors == 1
    assert not raw_path(cfg, Format.LEGACY, day).exists()


def test_server_error_is_retried(cfg: DataConfig) -> None:
    day = date(2023, 3, 1)
    answers = iter([httpx.Response(503), httpx.Response(200, content=ZIP_BYTES)])
    client, seen = fake_nse(lambda r: next(answers))
    summary = download_range(one_day(cfg, day), client, today=date(2026, 1, 1), sleep=no_sleep)

    assert summary.downloaded == 1
    assert len(seen) == 2


def test_resume_skips_done_work_but_rechecks_recent_404s(cfg: DataConfig) -> None:
    old, recent = date(2023, 3, 4), date(2025, 12, 30)
    today = date(2026, 1, 2)  # `recent` is within the 7-day re-check window
    for day in (old, recent):
        client, _ = fake_nse(lambda r: httpx.Response(404))
        download_range(one_day(cfg, day), client, today=today, sleep=no_sleep)

    client, seen = fake_nse(lambda r: httpx.Response(404))
    download_range(one_day(cfg, old), client, today=today, sleep=no_sleep)
    assert seen == []  # an old 404 is final

    download_range(one_day(cfg, recent), client, today=today, sleep=no_sleep)
    assert len(seen) == 1  # a recent 404 may just mean "not published yet"


def test_overlap_day_fetches_both_formats(cfg: DataConfig) -> None:
    day = date(2024, 3, 1)
    client, seen = fake_nse(lambda r: httpx.Response(200, content=ZIP_BYTES))
    download_range(one_day(cfg, day), client, today=date(2026, 1, 1), sleep=no_sleep)

    assert len(seen) == 2
    assert raw_path(cfg, Format.LEGACY, day).exists()
    assert raw_path(cfg, Format.UDIFF, day).exists()
