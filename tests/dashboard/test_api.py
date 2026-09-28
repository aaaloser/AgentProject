from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mokioclaw.dashboard.api import create_dashboard_app
from mokioclaw.dashboard.catalog import RepositoryCatalog
from mokioclaw.dashboard.git_reader import GitOutputLimit, GitReadTimeout, InvalidRepository, LocalGitReader
from mokioclaw.dashboard.pagination import CursorCodec


def _git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, check=True).stdout.decode().strip()


def _commit(root: Path, number: int, title: str | None = None) -> str:
    (root / "sample.txt").write_text(f"{number}\n", encoding="utf-8")
    _git(root, "add", "sample.txt")
    _git(root, "commit", "-q", "-m", title or f"commit {number}")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def api_setup(temp_git_repo: Path, tmp_path: Path):
    first = temp_git_repo
    second = tmp_path / "second"
    second.mkdir()
    _git(second, "init", "-q", "-b", "main")
    _git(second, "config", "user.name", "Fixture User")
    _git(second, "config", "user.email", "fixture@example.invalid")
    first_sha = _commit(first, 1, "<script>alert(1)</script>")
    second_sha = _commit(second, 2)
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([first, second], reader)
    client = TestClient(create_dashboard_app(catalog, reader, CursorCodec()), base_url="http://127.0.0.1")
    return client, catalog, first, second, first_sha, second_sha


def test_two_repositories_are_isolated_and_detail_is_json(api_setup) -> None:
    client, catalog, first, second, first_sha, second_sha = api_setup
    repos = client.get("/api/repositories").json()
    assert len(repos) == 2
    assert [row["path"] for row in repos] == [str(first), str(second)]
    first_id, second_id = [row["id"] for row in repos]
    page = client.get(f"/api/repositories/{first_id}/commits").json()
    assert [row["sha"] for row in page["commits"]] == [first_sha]
    assert page["anchor_sha"] == page["current_head_sha"] == first_sha
    assert page["next_cursor"] is None
    detail_response = client.get(f"/api/repositories/{first_id}/commits/{first_sha}", params={"anchor": first_sha})
    assert detail_response.status_code == 200
    assert detail_response.json()["assessment"]["sha"] == first_sha
    assert detail_response.json()["detail"]["title"] == "<script>alert(1)</script>"
    assert detail_response.headers["content-type"].startswith("application/json")
    assert client.get(f"/api/repositories/{first_id}/commits/{second_sha}", params={"anchor": first_sha}).status_code == 404
    assert client.get(f"/api/repositories/{second_id}/commits/{second_sha}", params={"anchor": second_sha}).status_code == 200


def test_cursor_keeps_anchor_when_head_advances(api_setup) -> None:
    client, _, first, _, _, _ = api_setup
    for number in range(2, 54):
        _commit(first, number)
    repo_id = client.get("/api/repositories").json()[0]["id"]
    page1 = client.get(f"/api/repositories/{repo_id}/commits").json()
    assert len(page1["commits"]) == 50
    assert page1["next_cursor"]
    new_head = _commit(first, 54)
    page2 = client.get(f"/api/repositories/{repo_id}/commits", params={"cursor": page1["next_cursor"]}).json()
    assert page2["anchor_sha"] == page1["anchor_sha"]
    assert page2["current_head_sha"] == new_head
    assert len(page2["commits"]) == 3
    assert page2["next_cursor"] is None
    assert all(row["sha"] != new_head for row in page2["commits"])
    second_id = client.get("/api/repositories").json()[1]["id"]
    cross_repo = client.get(f"/api/repositories/{second_id}/commits", params={"cursor": page1["next_cursor"]})
    assert cross_repo.status_code == 400
    assert cross_repo.json()["code"] == "invalid_cursor"


def test_bad_inputs_return_fixed_private_errors(api_setup) -> None:
    client, _, first, _, first_sha, second_sha = api_setup
    first_id, second_id = [row["id"] for row in client.get("/api/repositories").json()]
    cases = [
        ("/api/repositories/missing/commits", None, 404),
        (f"/api/repositories/{first_id}/commits", {"cursor": "not-a-cursor"}, 400),
        (f"/api/repositories/{first_id}/commits/{first_sha}", {"anchor": "HEAD"}, 400),
        (f"/api/repositories/{first_id}/commits/{first_sha}", None, 400),
        (f"/api/repositories/{first_id}/commits/{second_sha}", {"anchor": first_sha}, 404),
        (f"/api/repositories/{first_id}/commits/{'f' * 40}", {"anchor": first_sha}, 404),
        (f"/api/repositories/{second_id}/commits/{first_sha}", {"anchor": second_sha}, 404),
    ]
    for url, params, status in cases:
        response = client.get(url, params=params)
        assert response.status_code == status
        assert set(response.json()) == {"code", "message", "retryable"}
        assert str(first) not in response.text
        assert "Traceback" not in response.text
        assert "fatal:" not in response.text


def test_host_methods_and_security_headers(api_setup) -> None:
    client, _, _, _, _, _ = api_setup
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/api/repositories")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers
    assert client.get("/api/repositories", headers={"host": "attacker.example"}).status_code == 400
    for method in ("post", "put", "delete"):
        denied = getattr(client, method)("/api/repositories")
        assert denied.status_code == 405
        assert set(denied.json()) == {"code", "message", "retryable"}


@pytest.mark.parametrize("error_type", [GitReadTimeout, GitOutputLimit])
def test_git_limits_map_to_retryable_safe_error(api_setup, monkeypatch, error_type) -> None:
    client, _, first, _, _, _ = api_setup
    repo_id = client.get("/api/repositories").json()[0]["id"]
    original = LocalGitReader.list_commits

    def fail(self, root, anchor_sha, offset, limit=50):
        if root == first:
            raise error_type(f"secret path {first}")
        return original(self, root, anchor_sha, offset, limit)

    monkeypatch.setattr(LocalGitReader, "list_commits", fail)
    response = client.get(f"/api/repositories/{repo_id}/commits")
    assert response.status_code == 503
    assert response.json()["retryable"] is True
    assert str(first) not in response.text


@pytest.mark.parametrize("error_type", [GitReadTimeout, GitOutputLimit])
def test_detail_limit_never_assesses_incomplete_data(api_setup, monkeypatch, error_type) -> None:
    client, _, first, _, first_sha, second_sha = api_setup
    first_id, second_id = [row["id"] for row in client.get("/api/repositories").json()]
    original = LocalGitReader.get_commit

    def fail_first(self, root, sha, anchor_sha):
        if root == first:
            raise error_type("private Git output")
        return original(self, root, sha, anchor_sha)

    monkeypatch.setattr(LocalGitReader, "get_commit", fail_first)
    monkeypatch.setattr("mokioclaw.dashboard.api.assess_commit", lambda detail: pytest.fail("Incomplete data was assessed"))
    failed = client.get(f"/api/repositories/{first_id}/commits/{first_sha}", params={"anchor": first_sha})
    assert failed.status_code == 503
    assert set(failed.json()) == {"code", "message", "retryable"}
    assert "assessment" not in failed.text
    assert "private Git output" not in failed.text
    assert client.get(f"/api/repositories/{second_id}/commits").status_code == 200
    assert second_sha in client.get(f"/api/repositories/{second_id}/commits").text


def test_sha256_api_requires_full_length(tmp_path: Path) -> None:
    root = tmp_path / "sha256"
    root.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    initialized = subprocess.run(
        ["git", "init", "-q", "--object-format=sha256", "-b", "main", str(root)],
        capture_output=True, env=env,
    )
    if initialized.returncode != 0:
        pytest.skip("installed Git lacks SHA-256 object support")
    _git(root, "config", "user.name", "Fixture User")
    _git(root, "config", "user.email", "fixture@example.invalid")
    head = _commit(root, 1)
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([root], reader)
    client = TestClient(create_dashboard_app(catalog, reader, CursorCodec()), base_url="http://127.0.0.1")
    repo_id = catalog.summaries()[0].id
    valid = client.get(f"/api/repositories/{repo_id}/commits/{head}", params={"anchor": head})
    invalid = client.get(f"/api/repositories/{repo_id}/commits/{head[:40]}", params={"anchor": head})
    assert valid.status_code == 200
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_sha"


def test_detail_uses_process_cache_for_same_anchor(api_setup, monkeypatch) -> None:
    client, _, _, _, first_sha, _ = api_setup
    repo_id = client.get("/api/repositories").json()[0]["id"]
    url = f"/api/repositories/{repo_id}/commits/{first_sha}"
    first = client.get(url, params={"anchor": first_sha})
    assert first.status_code == 200

    def fail_if_read_again(*args, **kwargs):
        pytest.fail("Detail was read again")

    monkeypatch.setattr(LocalGitReader, "get_commit", fail_if_read_again)
    second = client.get(url, params={"anchor": first_sha})
    assert second.json() == first.json()


def test_empty_repository_has_no_anchor(temp_git_repo: Path) -> None:
    reader = LocalGitReader()
    catalog = RepositoryCatalog.from_paths([temp_git_repo], reader)
    client = TestClient(create_dashboard_app(catalog, reader, CursorCodec()), base_url="http://127.0.0.1")
    repo_id = client.get("/api/repositories").json()[0]["id"]
    response = client.get(f"/api/repositories/{repo_id}/commits")
    assert response.status_code == 200
    assert response.json() == {
        "repo_id": repo_id, "anchor_sha": None, "current_head_sha": None, "commits": [], "next_cursor": None,
    }


def test_unavailable_repository_does_not_break_other_repositories(api_setup, monkeypatch) -> None:
    client, _, first, _, _, _ = api_setup
    first_id, second_id = [row["id"] for row in client.get("/api/repositories").json()]
    original = LocalGitReader.inspect

    def moved(self, path):
        if path == first:
            raise InvalidRepository(f"secret path {first}")
        return original(self, path)

    monkeypatch.setattr(LocalGitReader, "inspect", moved)
    failed = client.get(f"/api/repositories/{first_id}/commits")
    assert failed.status_code == 503
    assert set(failed.json()) == {"code", "message", "retryable"}
    assert str(first) not in failed.text
    assert client.get(f"/api/repositories/{second_id}/commits").status_code == 200
