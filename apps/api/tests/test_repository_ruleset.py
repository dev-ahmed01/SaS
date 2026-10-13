"""Main protection must be active, reviewed and bound to required CI contexts."""
import copy
from unittest.mock import patch

import pytest

from app.repository_ruleset import (
    REPOSITORY,
    configured_policy,
    installed_policy,
    policy_is_strict,
    run,
)


def test_repo_ruleset_policy_requires_real_review_and_both_ci_jobs():
    policy = configured_policy()
    assert policy_is_strict(policy)
    assert policy["bypass_actors"] == []
    assert policy["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert {rule["type"] for rule in policy["rules"]} >= {
        "pull_request", "required_status_checks", "non_fast_forward", "deletion"
    }


@pytest.mark.parametrize("damage", [
    lambda p: p.update(enforcement="disabled"),
    lambda p: p.update(bypass_actors=[{"actor_id": 1}]),
    lambda p: p["conditions"]["ref_name"].update(include=["refs/heads/dev"]),
    lambda p: next(r for r in p["rules"] if r["type"] == "pull_request")[
        "parameters"
    ].update(required_approving_review_count=0),
    lambda p: next(r for r in p["rules"] if r["type"] == "pull_request")[
        "parameters"
    ].update(required_review_thread_resolution=False),
    lambda p: next(r for r in p["rules"] if r["type"] == "required_status_checks")[
        "parameters"
    ].update(required_status_checks=[{"context": "backend"}]),
    lambda p: p.update(rules=[r for r in p["rules"] if r["type"] != "non_fast_forward"]),
])
def test_weak_or_bypassed_ruleset_is_never_accepted(damage):
    policy = copy.deepcopy(configured_policy())
    damage(policy)
    assert policy_is_strict(policy) is False


def test_read_only_check_does_not_create_ruleset():
    with patch("app.repository_ruleset.installed_policy", return_value=(
        False, "Ruleset missing"
    )):
        assert run("check") is False
    with patch("app.repository_ruleset.installed_policy", return_value=(
        True, "Active main ruleset confirmed"
    )):
        assert run("check") is True


def test_admin_apply_requires_token_consent_and_sha():
    with patch("app.repository_ruleset.installed_policy", return_value=(
        False, "Ruleset missing"
    )):
        for kwargs in (
            {"token": "", "approve": REPOSITORY + ":main", "expected_sha": "a" * 40},
            {"token": "ci-only", "approve": "", "expected_sha": "a" * 40},
            {"token": "ci-only", "approve": REPOSITORY + ":main", "expected_sha": "a"},
        ):
            with pytest.raises(ValueError):
                run("apply", **kwargs)


def test_main_moving_blocks_ruleset_creation():
    with (
        patch("app.repository_ruleset.installed_policy", return_value=(
            False, "Ruleset missing"
        )),
        patch("app.repository_ruleset.github_json", return_value={
            "commit": {"sha": "b" * 40}
        }) as requester,
    ):
        with pytest.raises(RuntimeError, match="Main moved"):
            run(
                "apply", token="CI-FAKE", approve=REPOSITORY + ":main",
                expected_sha="a" * 40,
            )
        assert requester.call_count == 1
        assert requester.call_args.args[0] == "GET"


def test_successful_owner_apply_must_verify_real_installed_state():
    installed = [(False, "Ruleset missing"), (True, "Active main ruleset confirmed")]
    calls = []

    def query(method, endpoint, **kwargs):
        calls.append((method, endpoint))
        return {"commit": {"sha": "a" * 40}} if method == "GET" else {"id": 100}

    with (
        patch("app.repository_ruleset.installed_policy", side_effect=installed),
        patch("app.repository_ruleset.github_json", side_effect=query),
    ):
        assert run(
            "apply", token="TEST-NOT-A-REAL-TOKEN",
            approve=REPOSITORY + ":main", expected_sha="a" * 40,
        )
    assert calls == [("GET", "/branches/main"), ("POST", "/rulesets")]


def test_unverified_creation_never_counts_as_success():
    with (
        patch("app.repository_ruleset.installed_policy", side_effect=[
            (False, "Ruleset missing"), (False, "Ruleset missing"),
        ]),
        patch("app.repository_ruleset.github_json", side_effect=[
            {"commit": {"sha": "a" * 40}}, {"id": 100},
        ]),
    ):
        with pytest.raises(RuntimeError, match="not independently verified"):
            run(
                "apply", token="TEST-NOT-A-REAL-TOKEN",
                approve=REPOSITORY + ":main", expected_sha="a" * 40,
            )
