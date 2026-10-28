"""A VPS worker never sends from staging, just because a token exists."""
from types import SimpleNamespace

from app import saasyto_vps_worker as worker


def cfg(*, enabled=False, environment="staging"):
    return SimpleNamespace(
        app_env=environment,
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
        saasyto_worker_enabled=enabled,
    )


def test_worker_cannot_dispatch_in_staging_even_with_sender_flags(monkeypatch):
    monkeypatch.setattr(worker, "get_settings",
                        lambda: cfg(enabled=True, environment="staging"))
    monkeypatch.setattr(worker, "get_engine", lambda:
                        (_ for _ in ()).throw(AssertionError("DB must be untouched")))
    assert worker.dispatch_once() == 2
    assert worker.main(["--interval-seconds", "60"]) == 2


def test_production_sender_stays_off_without_worker_approval(monkeypatch):
    monkeypatch.setattr(worker, "get_settings",
                        lambda: cfg(enabled=False, environment="production"))
    monkeypatch.setattr(worker, "get_engine", lambda:
                        (_ for _ in ()).throw(AssertionError("No DB access")))
    assert worker.dispatch_once() == 2


def test_worker_uses_private_database_not_network_or_recipient_input(monkeypatch):
    monkeypatch.setattr(worker, "get_settings",
                        lambda: cfg(enabled=True, environment="production"))
    marker = object()
    monkeypatch.setattr(worker, "get_engine", lambda: marker)
    messages = []

    class FakeSession:
        def __init__(self, engine):
            assert engine is marker
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    monkeypatch.setattr(worker, "Session", FakeSession)
    monkeypatch.setattr(worker, "_reconcile_stale_claims", lambda db: 0)
    monkeypatch.setattr(worker, "_dispatch_due", lambda db, settings:
                        messages.append((db, settings)) or {"claimed": 1, "unknown": 1})
    assert worker.main(["--once"]) == 0
    assert len(messages) == 1


def test_worker_never_retries_exception_inside_same_tick(monkeypatch):
    monkeypatch.setattr(worker, "get_settings",
                        lambda: cfg(enabled=True, environment="production"))
    monkeypatch.setattr(worker, "get_engine", lambda: object())
    calls = []

    class FakeSession:
        def __init__(self, _engine):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    def fail(_db, _cfg):
        calls.append(1)
        raise OSError("synthetic unknown provider state")

    monkeypatch.setattr(worker, "Session", FakeSession)
    monkeypatch.setattr(worker, "_reconcile_stale_claims", lambda db: 0)
    monkeypatch.setattr(worker, "_dispatch_due", fail)
    assert worker.dispatch_once() == 1
    assert len(calls) == 1


def test_worker_reconciles_abandoned_claims_before_new_dispatch(monkeypatch, capsys):
    """Crash recovery must run even when no new recipients are due."""
    monkeypatch.setattr(worker, "get_settings",
                        lambda: cfg(enabled=True, environment="production"))
    monkeypatch.setattr(worker, "get_engine", lambda: object())
    steps = []

    class FakeSession:
        def __init__(self, _engine):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    def reconcile(_db):
        steps.append("reconciled")
        return 2

    def dispatch(_db, _cfg):
        steps.append("dispatch")
        return {}

    monkeypatch.setattr(worker, "Session", FakeSession)
    monkeypatch.setattr(worker, "_reconcile_stale_claims", reconcile)
    monkeypatch.setattr(worker, "_dispatch_due", dispatch)
    assert worker.dispatch_once() == 0
    assert steps == ["reconciled", "dispatch"]
    assert '"reconciled_unknown": 2' in capsys.readouterr().out


def test_worker_does_not_dispatch_if_reconciliation_fails(monkeypatch):
    """An interrupted claim cannot be ignored to continue sending."""
    monkeypatch.setattr(worker, "get_settings",
                        lambda: cfg(enabled=True, environment="production"))
    monkeypatch.setattr(worker, "get_engine", lambda: object())

    class FakeSession:
        def __init__(self, _engine):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    def fail(_db):
        raise RuntimeError("synthetic recovery failure")

    monkeypatch.setattr(worker, "Session", FakeSession)
    monkeypatch.setattr(worker, "_reconcile_stale_claims", fail)
    monkeypatch.setattr(worker, "_dispatch_due",
                        lambda *_: (_ for _ in ()).throw(
                            AssertionError("Must not send when recovery fails")))
    assert worker.dispatch_once() == 1
