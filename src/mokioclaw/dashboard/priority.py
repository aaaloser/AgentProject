from __future__ import annotations

from mokioclaw.dashboard.models import CommitDetail, ReviewAssessment, ReviewReason


RULE_VERSION = "review-priority-v1"
SENSITIVE_SEGMENTS = frozenset({"auth", "authorization", "permission", "permissions", "security", "approval"})
SENSITIVE_FILENAMES = frozenset(
    {
        "pyproject.toml", "setup.py", "uv.lock", "poetry.lock", "pipfile.lock", "package.json",
        "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    }
)


def _normalized(path: str) -> str:
    return path.replace("\\", "/").strip("/").casefold()


def _sensitive(path: str) -> bool:
    normalized = _normalized(path)
    parts = normalized.split("/")
    filename = parts[-1]
    return (
        any(part in SENSITIVE_SEGMENTS for part in parts)
        or filename in SENSITIVE_FILENAMES
        or filename.startswith("dockerfile")
        or (filename.startswith("requirements") and filename.endswith(".txt"))
        or normalized.startswith(".github/workflows/")
    )


def _test_path(path: str) -> bool:
    normalized = _normalized(path)
    filename = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("tests/") or filename.startswith("test_") or filename.endswith("_test.py")


def assess_commit(detail: CommitDetail) -> ReviewAssessment:
    file_count = len(detail.files)
    is_merge = len(detail.parent_shas) > 1
    incomplete = detail.stats_unavailable_reason is not None or any(
        item.additions is None or item.deletions is None or item.change_type == "unknown" for item in detail.files
    )
    changed_lines = None if is_merge or incomplete else sum((item.additions or 0) + (item.deletions or 0) for item in detail.files)
    deleted_or_renamed = any(item.change_type in {"deleted", "renamed"} for item in detail.files)
    sensitive = any(_sensitive(path) for item in detail.files for path in (item.path, item.previous_path) if path is not None)
    tests_changed = any(_test_path(item.path) for item in detail.files)
    signals: dict[str, object] = {
        "changed_files": file_count,
        "changed_lines": changed_lines,
        "deleted_or_renamed": deleted_or_renamed,
        "sensitive_path": sensitive,
        "tests_changed": tests_changed,
    }
    limitations = ["ci_not_checked", "tests_not_run"]
    if detail.stats_unavailable_reason is not None:
        limitations.append(detail.stats_unavailable_reason)

    if is_merge or incomplete:
        reasons = []
        if is_merge:
            reasons.append(ReviewReason("merge_commit", "合并提交超出本规则的单父差异范围，需人工审查。"))
        if incomplete:
            reasons.append(ReviewReason("incomplete_stats", "文件统计不完整或为二进制内容，需人工审查。"))
        return ReviewAssessment(detail.sha, RULE_VERSION, "manual_review", signals, tuple(reasons), tuple(limitations))

    reasons = []
    if sensitive:
        reasons.append(ReviewReason("sensitive_path", "改动涉及依赖、构建、权限或 CI 等需优先审查的位置。"))
    if file_count >= 10:
        reasons.append(ReviewReason("many_files", f"改动涉及 {file_count} 个文件。"))
    if changed_lines is not None and changed_lines >= 500:
        reasons.append(ReviewReason("large_diff", f"增加和删除合计 {changed_lines} 行。"))
    high = bool(reasons)
    if file_count >= 4 and file_count < 10:
        reasons.append(ReviewReason("several_files", f"改动涉及 {file_count} 个文件。"))
    if changed_lines is not None and 120 <= changed_lines < 500:
        reasons.append(ReviewReason("moderate_diff", f"增加和删除合计 {changed_lines} 行。"))
    if deleted_or_renamed:
        reasons.append(ReviewReason("deleted_or_renamed", "存在文件删除或重命名，需要核对引用。"))
    priority = "high" if high else "medium" if reasons else "low"
    return ReviewAssessment(detail.sha, RULE_VERSION, priority, signals, tuple(reasons), tuple(limitations))
