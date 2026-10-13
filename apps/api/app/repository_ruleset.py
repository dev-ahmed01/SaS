"""Owner-operated, fail-closed GitHub main ruleset installer and verifier.

This script cannot use the GitHub App's limited permission by itself.
It requires a separate repository-administration credential for --apply.
It never logs authorization headers or response bodies.
"""
import argparse
import json
import os
import re
from pathlib import Path
from urllib import error, request

REPOSITORY = "dev-ahmed01/SaS"
RULESET_NAME = "SaS main release safeguards"
API_ROOT = "https://api.github.com/repos/" + REPOSITORY
POLICY_PATH = Path(__file__).resolve().parents[3] / "ops/github/main-ruleset.json"
REQUIRED = {"backend", "frontend"}
SHA = re.compile(r"^[a-f0-9]{40}$")


def configured_policy() -> dict:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not policy_is_strict(policy):
        raise ValueError("Local main ruleset is incomplete or unsafe")
    return policy


def policy_is_strict(policy: object) -> bool:
    """Require essential controls; allow GitHub to add server-side fields."""
    if not isinstance(policy, dict):
        return False
    if (
        policy.get("name") != RULESET_NAME
        or policy.get("target") != "branch"
        or policy.get("enforcement") != "active"
        or policy.get("bypass_actors", []) != []
        or policy.get("conditions", {}).get("ref_name", {}) != {
            "include": ["refs/heads/main"], "exclude": []
        }
    ):
        return False
    rules = policy.get("rules")
    if not isinstance(rules, list):
        return False
    keyed = {rule.get("type"): rule for rule in rules if isinstance(rule, dict)}
    if not {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(keyed):
        return False
    reviews = keyed["pull_request"].get("parameters", {})
    status = keyed["required_status_checks"].get("parameters", {})
    if (
        reviews.get("required_approving_review_count", 0) < 1
        or reviews.get("dismiss_stale_reviews_on_push") is not True
        or reviews.get("required_review_thread_resolution") is not True
        or status.get("strict_required_status_checks_policy") is not True
    ):
        return False
    checks = status.get("required_status_checks", [])
    return isinstance(checks, list) and REQUIRED <= {
        check.get("context") for check in checks if isinstance(check, dict)
    }


def github_json(method: str, path: str, *, token: str = "", payload: dict | None = None):
    """Fixed-origin GitHub endpoint. Error messages never include private data."""
    if method not in {"GET", "POST"} or not path.startswith("/") or ".." in path:
        raise ValueError("Unsupported GitHub request")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SaS-protected-main-auditor",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(API_ROOT + path, headers=headers, data=data, method=method)
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        if isinstance(exc, error.HTTPError):
            raise RuntimeError(
                "GitHub request failed (HTTP " + str(exc.code) + ")"
            ) from None
        raise RuntimeError("GitHub ruleset network request failed") from None


def installed_policy(token: str = "") -> tuple[bool, str]:
    """Do not mistake a disabled, bypassed or weaker ruleset for protection."""
    found = github_json("GET", "/rulesets?includes_parents=false", token=token)
    if not isinstance(found, list):
        raise RuntimeError("GitHub ruleset list had an unexpected shape")
    ours = [entry for entry in found if entry.get("name") == RULESET_NAME]
    if len(ours) > 1:
        raise RuntimeError("Duplicate main ruleset names require manual review")
    if not ours:
        return False, "Ruleset missing"
    identifier = ours[0].get("id")
    if not isinstance(identifier, int) or identifier < 1:
        raise RuntimeError("Invalid ruleset identifier")
    details = github_json("GET", "/rulesets/" + str(identifier), token=token)
    if not policy_is_strict(details):
        return False, "Ruleset exists but required safeguards are not active"
    return True, "Active main ruleset confirmed"


def run(mode: str, *, token: str = "", expected_sha: str = "", approve: str = "") -> bool:
    policy = configured_policy()
    present, description = installed_policy(token)
    if present:
        print(description)
        return True
    if mode == "check":
        print("Main branch ruleset NOT VERIFIED: " + description)
        return False
    if mode != "apply":
        raise ValueError("Unsupported operation")
    if not token:
        raise ValueError("Owner administration token required (GITHUB_TOKEN)")
    if approve != REPOSITORY + ":main" or not SHA.fullmatch(expected_sha):
        raise ValueError("Explicit repo:branch confirmation and head SHA required")
    if description != "Ruleset missing":
        raise RuntimeError("Existing incompatible ruleset requires manual admin review")
    branch = github_json("GET", "/branches/main", token=token)
    if branch.get("commit", {}).get("sha") != expected_sha:
        raise RuntimeError("Main moved; inspect changes before retrying")
    github_json("POST", "/rulesets", token=token, payload=policy)
    verified, _ = installed_policy(token)
    if not verified:
        raise RuntimeError("Ruleset created but not independently verified")
    print("Active main ruleset confirmed; deployment and messaging remain disabled")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or owner-apply a strict SaS main branch ruleset."
    )
    parser.add_argument("mode", choices=("check", "apply"))
    parser.add_argument("--expected-main-sha", default="")
    parser.add_argument("--approve", default="")
    args = parser.parse_args()
    try:
        ok = run(
            args.mode,
            token=os.environ.get("GITHUB_TOKEN", ""),
            expected_sha=args.expected_main_sha,
            approve=args.approve,
        )
        return 0 if ok else 1
    except (ValueError, RuntimeError) as exc:
        # Never print GitHub API body, personal token, or request URL.
        print("Main protection NOT VERIFIED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
