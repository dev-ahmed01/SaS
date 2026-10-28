"""No-network tests for the scheduled or supervised Saasyto private worker."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "saasyto_tick.py"


@pytest.fixture
def worker():
    spec = importlib.util.spec_from_file_location("sas_private_worker_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cron_default_runs_exactly_one_tick_without_network(worker, monkeypatch):
    ticks = []
    monkeypatch.setattr(worker, "run_once", lambda: ticks.append("tick") or 0)
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("cron must not sleep"))
    assert worker.main([]) == 0
    assert ticks == ["tick"]


def test_supervised_mode_repeats_only_at_bounded_cadence(worker, monkeypatch):
    ticks = []
    sleeps = []
    monkeypatch.setattr(worker, "run_once", lambda: ticks.append("tick") or 0)

    def stop_on_sleep(seconds):
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.time, "sleep", stop_on_sleep)
    assert worker.main(["--loop", "--interval-seconds", "60"]) == 0
    assert ticks == ["tick"]
    assert sleeps == [60]


def test_bad_configuration_stops_supervised_worker(worker, monkeypatch):
    ticks = []
    monkeypatch.setattr(worker, "run_once", lambda: ticks.append("tick") or 2)
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("must not sleep"))
    assert worker.main(["--loop"]) == 2
    assert ticks == ["tick"]


@pytest.mark.parametrize("seconds", ["0", "1", "3601", "-1"])
def test_worker_rejects_unsafe_cadence(worker, seconds):
    with pytest.raises(SystemExit):
        worker.main(["--loop", "--interval-seconds", seconds])
