from pathlib import Path

from development_aide import (
    build_code_review_report,
    build_error_fix_report,
    build_multi_file_summary,
    build_project_summary,
    build_quick_audit,
    collect_project_files,
    detect_common_issues,
    format_response,
)


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
