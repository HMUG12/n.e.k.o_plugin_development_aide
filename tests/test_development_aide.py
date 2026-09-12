import asyncio
import os

import pytest
from development_aide import (
    DEFAULT_MAX_CHARS,
    MAX_CHARS_HARD_LIMIT,
    DevelopmentAidePlugin,
    Err,
    Ok,
    build_code_review_report,
    build_error_fix_report,
    build_multi_file_summary,
    build_project_summary,
    build_quick_audit,
    coerce_read_limit,
    collect_project_files,
    collect_project_files_budgeted,
    detect_common_issues,
    format_response,
    read_project_members,
    read_text_limited,
    resolve_member_path,
    resolve_scan_root,
)

# ---------------------------------------------------------------------------
# Pure report builders
# ---------------------------------------------------------------------------


def test_collect_project_files_filters_extensions(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "src" / "guide.md").write_text("hello\n", encoding="utf-8")
    (tmp_path / "src" / "image.png").write_bytes(b"binary")

    files = collect_project_files(tmp_path, extensions={".py", ".md"})

    assert "src/main.py" in files
    assert "src/guide.md" in files
    assert "src/image.png" not in files


def test_detect_common_issues_flags_todos_and_hardcoded_paths():
    content = "import os\n# TODO: fix later\nprint('/tmp/secret.txt')\n"

    issues = detect_common_issues(content, "demo.py")

    assert any("TODO" in issue.upper() for issue in issues)
    assert any("hardcoded" in issue.lower() for issue in issues)


def test_build_project_summary_returns_sections():
    files = [
        "app/main.py",
        "app/ui/settings.tsx",
        "README.md",
    ]

    summary = build_project_summary(files, "/tmp/demo")

    assert "project_root" in summary
    assert "files" in summary
    assert len(summary["files"]) >= 3
    assert "summary" in summary


def test_build_code_review_report_and_fix_report():
    files = {
        "app/main.py": "import os\n# TODO: fix later\nprint('/tmp/test')\n",
        "README.md": "# Demo\n",
    }

    review = build_code_review_report(files)
    fix = build_error_fix_report(files)

    assert "review" in review
    assert "issues" in review
    assert "fixes" in fix
    assert len(fix["fixes"]) >= 1


def test_multi_file_summary_and_tone_formatting():
    files = {
        "app/main.py": "print('hello')\n",
        "app/api.py": "# TODO: cleanup\n",
    }

    summary = build_multi_file_summary(files)
    formatted = format_response(summary["summary"], "catgirl")

    assert "project" in summary
    assert "summary" in summary
    assert "meow" in formatted.lower() or "nya" in formatted.lower() or "catgirl" in formatted.lower()


def test_quick_audit_combines_review_fix_and_summary():
    files = {
        "app/main.py": "import os\n# TODO: fix later\nprint('/tmp/test')\n",
        "app/api.py": "print('hi')\n",
    }

    audit = build_quick_audit(files)

    assert "review" in audit
    assert "fixes" in audit
    assert "structure" in audit
    assert "formatted" in audit


# ---------------------------------------------------------------------------
# Issue #1: workspace path sandbox
# ---------------------------------------------------------------------------


def test_resolve_member_path_rejects_traversal_absolute_and_empty(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "outside.txt").write_text("no", encoding="utf-8")

    assert resolve_member_path(str(workspace), "../outside.txt") is None
    assert resolve_member_path(str(workspace), str(tmp_path / "outside.txt")) is None
    assert resolve_member_path(str(workspace), "") is None
    assert resolve_member_path(str(workspace), "   ") is None
    assert resolve_member_path("", "a.py") is None

    (workspace / "a.py").write_text("ok", encoding="utf-8")
    resolved = resolve_member_path(str(workspace), "a.py")
    assert resolved is not None
    assert os.path.samefile(resolved, str(workspace / "a.py"))


def test_resolve_scan_root_rejects_escaping_subpaths(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()

    assert resolve_scan_root(str(workspace), str(tmp_path)) is None
    assert resolve_scan_root(str(workspace), "../..") is None
    assert resolve_scan_root(str(workspace)) == os.path.realpath(str(workspace))


def test_scan_skips_symlink_escaping_workspace(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "keep.py").write_text("KEEP = 1\n", encoding="utf-8")
    try:
        os.symlink(str(outside), str(workspace / "link"), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this host")

    files, _ = collect_project_files_budgeted(str(workspace))

    assert "keep.py" in files
    assert all("secret" not in name for name in files)
    assert resolve_member_path(str(workspace), os.path.join("link", "secret.py")) is None


# ---------------------------------------------------------------------------
# Issue #5: bounded reads, scans and batch budgets
# ---------------------------------------------------------------------------


def test_coerce_read_limit_validates_and_caps():
    assert coerce_read_limit(None) == (DEFAULT_MAX_CHARS, False)
    assert coerce_read_limit(100) == (100, False)
    assert coerce_read_limit(MAX_CHARS_HARD_LIMIT + 1) == (MAX_CHARS_HARD_LIMIT, True)

    for bad in (0, -5, True, False, "abc", [1]):
        with pytest.raises(ValueError):
            coerce_read_limit(bad)


def test_read_text_limited_bounds_disk_reads(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("y" * 100, encoding="utf-8")

    text, truncated = read_text_limited(str(path), 25)
    assert text == "y" * 25
    assert truncated is True

    full, truncated_full = read_text_limited(str(path), 100)
    assert full == "y" * 100
    assert truncated_full is False


def test_read_project_members_respects_total_budget(tmp_path):
    names = []
    for index in range(3):
        name = f"f{index}.txt"
        (tmp_path / name).write_text("z" * 100, encoding="utf-8")
        names.append(name)

    contents, meta = read_project_members(
        str(tmp_path),
        names,
        per_file_limit=50,
        total_limit=60,
        max_files=25,
    )

    assert meta["chars_read"] <= 60
    assert meta["total_budget_truncated"] is True
    assert set(contents).issubset(set(names))


def test_read_project_members_caps_file_count(tmp_path):
    names = [f"m{index}.txt" for index in range(30)]
    for name in names:
        (tmp_path / name).write_text("a", encoding="utf-8")

    _, meta = read_project_members(
        str(tmp_path),
        names,
        per_file_limit=10,
        total_limit=10_000,
        max_files=25,
    )

    assert meta["files_requested"] == 30
    assert meta["file_count_truncated"] is True
    assert meta["files_read"] == 25


def test_collect_project_files_budgeted_reports_truncation(tmp_path):
    for index in range(3):
        (tmp_path / f"a{index}.py").write_text("# x\n", encoding="utf-8")

    files, meta = collect_project_files_budgeted(
        str(tmp_path), extensions=[".py"], max_files=2, max_dirs=10
    )

    assert len(files) == 2
    assert meta["scan_truncated"] is True


# ---------------------------------------------------------------------------
# Plugin-level behaviour: #1 sandbox, #4 persistence, #6 feature gates
# ---------------------------------------------------------------------------


def _make_plugin() -> DevelopmentAidePlugin:
    return DevelopmentAidePlugin(None)


def _save_config(plugin: DevelopmentAidePlugin, **overrides) -> dict:
    config = {
        "skill_path": "",
        "workspace_root": "",
        "read_only": True,
        "max_chars": 4000,
        "analysis_tone": "professional",
        "enable_code_review": True,
        "enable_error_fix": True,
        "enable_project_summary": True,
        "enable_multi_file_summary": True,
    }
    config.update(overrides)
    return asyncio.run(plugin.save_settings(config=config))


def test_entries_without_workspace_are_blocked():
    plugin = _make_plugin()

    assert isinstance(asyncio.run(plugin.list_project_files()), Err)
    assert isinstance(asyncio.run(plugin.read_project_file(relative_path="a.py")), Err)


def test_read_project_file_sandbox_and_per_file_limit(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    plugin = _make_plugin()
    assert isinstance(_save_config(plugin, workspace_root=str(workspace)), Ok)

    blocked = asyncio.run(plugin.read_project_file(relative_path="../outside.txt"))
    blocked_abs = asyncio.run(
        plugin.read_project_file(relative_path=str(tmp_path / "outside.txt"))
    )
    assert isinstance(blocked, Err)
    assert isinstance(blocked_abs, Err)

    bad_limit = asyncio.run(plugin.read_project_file(relative_path="a.py", max_chars=-1))
    assert isinstance(bad_limit, Err)

    ok = asyncio.run(plugin.read_project_file(relative_path="a.py", max_chars=10))
    assert isinstance(ok, Ok)
    assert ok["content"] == "x" * 10
    assert ok["truncated"] is True


def test_save_settings_rejects_invalid_config():
    plugin = _make_plugin()

    assert isinstance(_save_config(plugin, workspace_root="relative/path"), Err)
    assert isinstance(_save_config(plugin, max_chars=0), Err)
    assert isinstance(_save_config(plugin, max_chars=-3), Err)
    assert isinstance(_save_config(plugin, max_chars="abc"), Err)
    assert isinstance(_save_config(plugin, analysis_tone="sarcastic"), Err)


def test_settings_persist_across_reload(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plugin = _make_plugin()
    result = _save_config(
        plugin,
        workspace_root=str(workspace),
        max_chars=2500,
        analysis_tone="catgirl",
        enable_error_fix=False,
    )
    assert isinstance(result, Ok)

    # Simulate a host restart: a fresh instance backed by the same config store.
    restarted = _make_plugin()
    restarted.config = plugin.config
    asyncio.run(restarted._reload_settings())

    assert restarted.workspace_root == str(workspace)
    assert restarted.max_chars == 2500
    assert restarted.analysis_tone == "catgirl"
    assert restarted.enable_error_fix is False
    assert restarted.enable_code_review is True


def test_disabled_feature_entries_are_blocked(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("# TODO: fix\n", encoding="utf-8")
    plugin = _make_plugin()
    saved = _save_config(
        plugin,
        workspace_root=str(workspace),
        enable_code_review=False,
        enable_error_fix=False,
        enable_project_summary=False,
        enable_multi_file_summary=False,
    )
    assert isinstance(saved, Ok)

    assert isinstance(asyncio.run(plugin.code_review()), Err)
    assert isinstance(asyncio.run(plugin.error_fix()), Err)
    assert isinstance(asyncio.run(plugin.project_summary()), Err)
    assert isinstance(asyncio.run(plugin.multi_file_summary()), Err)
    assert isinstance(asyncio.run(plugin.quick_audit()), Err)


def test_code_review_runs_when_enabled(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "app").mkdir()
    (workspace / "app" / "main.py").write_text(
        "# TODO: fix me\nprint('/tmp/x')\n", encoding="utf-8"
    )
    plugin = _make_plugin()
    assert isinstance(_save_config(plugin, workspace_root=str(workspace)), Ok)

    result = asyncio.run(plugin.code_review())

    assert isinstance(result, Ok)
    assert result["report"]["issue_count"] >= 1
    assert "budget" in result["report"]
