from __future__ import annotations

from dataclasses import asdict

import pytest

from mokioclaw.dashboard.models import ChangedFile, CommitDetail
from mokioclaw.dashboard.priority import assess_commit


SHA = "a" * 40


def detail(*files: ChangedFile, parents: tuple[str, ...] = ("b" * 40,)) -> CommitDetail:
    return CommitDetail(
        sha=SHA,
        title="A title that must not affect priority",
        committed_at="2026-09-26T10:00:00+08:00",
        parent_shas=parents,
        files=files,
    )


def changed(path: str, *, additions: int | None = 1, deletions: int | None = 0, change_type: str = "modified", previous_path: str | None = None) -> ChangedFile:
    return ChangedFile(path=path, previous_path=previous_path, change_type=change_type, additions=additions, deletions=deletions)


@pytest.mark.parametrize(
    ("file_count", "priority"),
    [(3, "low"), (4, "medium"), (9, "medium"), (10, "high")],
)
def test_priority_file_count_boundaries(file_count: int, priority: str) -> None:
    files = [changed(f"src/module_{index}.py") for index in range(file_count)]
    assert assess_commit(detail(*files)).priority == priority


@pytest.mark.parametrize(
    ("lines", "priority"),
    [(119, "low"), (120, "medium"), (499, "medium"), (500, "high")],
)
def test_priority_line_count_boundaries(lines: int, priority: str) -> None:
    assert assess_commit(detail(changed("src/module.py", additions=lines))).priority == priority


def test_priority_reasons_have_stable_order_and_rule_version() -> None:
    files = [changed("src/auth/login.py", additions=500)]
    files.extend(changed(f"src/module_{index}.py") for index in range(9))
    assessment = assess_commit(detail(*files))

    assert assessment.rule_version == "review-priority-v1"
    assert assessment.sha == SHA
    assert assessment.priority == "high"
    assert [reason.code for reason in assessment.reasons] == ["sensitive_path", "many_files", "large_diff"]
    assert assessment.signals["changed_files"] == 10
    assert assessment.signals["changed_lines"] == 509
    assert "ci_not_checked" in assessment.limitations


@pytest.mark.parametrize(
    ("path", "priority"),
    [
        ("src/auth/login.py", "high"),
        ("auth", "high"),
        ("src/author/login.py", "low"),
        ("src/permissions/edit.py", "high"),
        ("requirements-dev.txt", "high"),
        (".github/workflows/check.yml", "high"),
        ("src/.github/workflows/check.yml", "low"),
        ("Dockerfile.dev", "high"),
    ],
)
def test_sensitive_paths_are_exact_segments_or_fixed_names(path: str, priority: str) -> None:
    assert assess_commit(detail(changed(path))).priority == priority


def test_manual_review_precedes_high_for_merge_binary_and_missing_stats() -> None:
    merge = assess_commit(detail(changed("src/auth/x.py"), parents=("b" * 40, "c" * 40)))
    binary = assess_commit(detail(changed("image.png", additions=None, deletions=None)))
    incomplete = assess_commit(detail(changed("src/x.py", additions=3, deletions=None)))

    assert merge.priority == binary.priority == incomplete.priority == "manual_review"
    assert [reason.code for reason in merge.reasons] == ["merge_commit"]
    assert [reason.code for reason in binary.reasons] == ["incomplete_stats"]
    assert [reason.code for reason in incomplete.reasons] == ["incomplete_stats"]
    assert merge.signals["changed_lines"] is None


def test_deletion_and_rename_need_medium_review() -> None:
    deletion = assess_commit(detail(changed("src/old.py", change_type="deleted", additions=0, deletions=1)))
    rename = assess_commit(detail(changed("src/new.py", previous_path="src/old.py", change_type="renamed", additions=0, deletions=0)))
    assert deletion.priority == rename.priority == "medium"
    assert [reason.code for reason in deletion.reasons] == ["deleted_or_renamed"]


def test_test_file_signal_does_not_change_priority() -> None:
    assessment = assess_commit(detail(changed("tests/test_widget.py")))
    assert assessment.priority == "low"
    assert assessment.signals["tests_changed"] is True
    assert assessment.reasons == ()


def test_assessment_ignores_cwd_timezone_and_title(tmp_path, monkeypatch) -> None:
    before = asdict(assess_commit(detail(changed("src/feature.py", additions=5))))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TZ", "UTC")
    other = detail(changed("src/feature.py", additions=5))
    other = CommitDetail(sha=other.sha, title="Different title", committed_at="2020-01-01T00:00:00Z", parent_shas=other.parent_shas, files=other.files)
    assert asdict(assess_commit(other)) == before
