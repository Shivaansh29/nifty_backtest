"""`nifty-backtest study` picks the loader from the plan's schema_version (M9 plan §9.4)."""

from pathlib import Path

import pytest

from nifty_backtest.cli import main
from nifty_backtest.research import condor_study, study


def test_schema_2_plans_go_to_the_m9_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Path, Path]] = []
    monkeypatch.setattr(
        condor_study, "run_condor_study", lambda p, r, *a, **k: calls.append(("m9", p, r))
    )
    monkeypatch.setattr(study, "run_study", lambda p, r, *a, **k: calls.append(("m7", p, r)))
    assert main(["study", "docs/research/m9_plan.toml"]) == 0
    assert main(["study"]) == 0
    assert calls == [
        ("m9", Path("docs/research/m9_plan.toml"), Path("docs/research/m9_iron_condor_plan.md")),
        ("m7", Path("docs/research/m7_plan.toml"), Path("docs/research/m7_preregistration.md")),
    ]
