from __future__ import annotations

import asyncio
import os
import re
from typing import Any

try:
    from plugin.sdk.plugin import (
        Err,
        NekoPluginBase,
        Ok,
        SdkError,
        lifecycle,
        neko_plugin,
        plugin_entry,
        tr,
        ui,
    )
except ImportError:  # pragma: no cover - fallback for tests and standalone import
    class SdkError(RuntimeError):
        pass

    class Ok(dict):
        def __init__(self, data: Any = None):
            super().__init__(data if isinstance(data, dict) else {})

    class Err(dict):
        def __init__(self, error: Any = None):
            super().__init__()
            self.error = error

    class _InMemoryConfig:
        """Minimal stand-in for the SDK PluginConfig facade."""

        def __init__(self, initial: dict | None = None):
            self._data: dict[str, Any] = {"settings": dict(initial or {})}

        async def dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"settings": dict(self._data.get("settings", {}))}

        async def set(self, path: str, value: Any, *args: Any, **kwargs: Any) -> None:
            parts = [part for part in str(path).split(".") if part]
            current = self._data
            for part in parts[:-1]:
                nxt = current.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    current[part] = nxt
                current = nxt
            current[parts[-1]] = value

        async def update(self, patch: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            for key, value in (patch or {}).items():
                self._data[key] = value
            return await self.dump()

    class NekoPluginBase:
        def __init__(self, ctx: Any = None):
            self.ctx = ctx
            self.config = _InMemoryConfig()
            self.logger = type(
                "Logger",
                (),
                {
                    "exception": lambda self, *args, **kwargs: None,
                    "warning": lambda self, *args, **kwargs: None,
                    "info": lambda self, *args, **kwargs: None,
                },
            )()

    def neko_plugin(cls):
        return cls

    def lifecycle(id=None):
        def decorator(fn):
            return fn
        return decorator

    def plugin_entry(**_):
        def decorator(fn):
            return fn
        return decorator

    def tr(key: str, default: str | None = None):
        return default if default is not None else key

    class _Ui:
        def action(self, **_):
            def decorator(fn):
                return fn
            return decorator

        def context(self, **_):
            def decorator(fn):
                return fn
            return decorator

    ui = _Ui()


# ---------------------------------------------------------------------------
# Bounded resource budgets (issue #5: limits must bound actual reads/walks)
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS = (".py", ".ts", ".tsx", ".md", ".toml", ".json")
DEFAULT_MAX_CHARS = 4000
MAX_CHARS_HARD_LIMIT = 1_000_000
MAX_BATCH_FILES = 25
MAX_BATCH_TOTAL_CHARS = 50_000
MAX_SCAN_FILES = 500
MAX_SCAN_DIRS = 200


def _normalize_extensions(extensions: Any | None) -> set[str]:
    """Normalize and validate file extensions."""
    if not extensions:
        return set(DEFAULT_EXTENSIONS)
    normalized: set[str] = set()
    for ext in extensions:
        value = str(ext).strip()
        if not value:
            continue
        normalized.add(value if value.startswith(".") else f".{value}")
    return normalized or set(DEFAULT_EXTENSIONS)


def coerce_read_limit(value: Any, default: int = DEFAULT_MAX_CHARS) -> tuple[int, bool]:
    """Validate a per-file character budget.

    Zero and negative values are rejected. Absurdly large values are capped to
    the hard limit. Returns ``(limit, capped)``.
    """
    raw = default if value is None else value
    if isinstance(raw, bool):
        raise ValueError("max_chars 必须是正整数。")
    try:
        number = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_chars 必须是正整数。") from exc
    if number <= 0:
        raise ValueError("max_chars 必须是大于 0 的正整数。")
    return min(number, MAX_CHARS_HARD_LIMIT), number > MAX_CHARS_HARD_LIMIT


# ---------------------------------------------------------------------------
# Workspace path sandbox (issue #1: no traversal / links escape the workspace)
# ---------------------------------------------------------------------------

def _is_within(target: str, root: str) -> bool:
    """True when ``target`` equals or lives below ``root`` (real, normalized)."""
    root_norm = os.path.normcase(os.path.normpath(root)).rstrip(os.sep)
    target_norm = os.path.normcase(os.path.normpath(target))
    return target_norm == root_norm or target_norm.startswith(root_norm + os.sep)


def _real_root(root: Any) -> str | None:
    """Resolve the configured workspace root; empty/unset is rejected.

    An empty string must never fall through to abspath() (which would turn it
    into the process working directory).
    """
    if isinstance(root, os.PathLike):
        root = os.fspath(root)
    if not isinstance(root, str) or not root.strip():
        return None
    return os.path.realpath(os.path.abspath(root))


def resolve_scan_root(root: str, relative_path: str = "") -> str | None:
    """Resolve a scan directory, rejecting absolute paths and link escapes."""
    base = _real_root(root)
    if base is None:
        return None
    rel = relative_path or ""
    if "\x00" in rel or os.path.isabs(rel):
        return None
    candidate = os.path.realpath(os.path.abspath(os.path.join(base, rel))) if rel else base
    return candidate if _is_within(candidate, base) else None


def resolve_member_path(root: str, relative_path: str) -> str | None:
    """Resolve a single member file, rejecting traversal and link escapes."""
    base = _real_root(root)
    if base is None or not isinstance(relative_path, str) or not relative_path.strip():
        return None
    if "\x00" in relative_path or os.path.isabs(relative_path):
        return None
    candidate = os.path.realpath(os.path.abspath(os.path.join(base, relative_path)))
    return candidate if _is_within(candidate, base) else None


def collect_project_files_budgeted(
    root: str,
    relative_path: str = "",
    extensions: Any | None = None,
    *,
    max_files: int = MAX_SCAN_FILES,
    max_dirs: int = MAX_SCAN_DIRS,
) -> tuple[list[str], dict[str, Any]]:
    """Collect project files with extension filtering and traversal budgets.

    Symlinks/junctions are never descended; every matched file is re-checked
    against the workspace after realpath resolution.
    """
    scan_root = resolve_scan_root(root, relative_path)
    if scan_root is None or not os.path.isdir(scan_root):
        return [], {"exists": False, "dirs_scanned": 0, "file_count": 0, "scan_truncated": False}

    base = os.path.realpath(os.path.abspath(root))
    allowed = _normalize_extensions(extensions)
    files: list[str] = []
    dirs_scanned = 0
    truncated_files = False
    truncated_dirs = False

    for dirpath, dirnames, filenames in os.walk(scan_root, followlinks=False):
        dirs_scanned += 1
        if dirs_scanned > max_dirs:
            truncated_dirs = True
            break
        # Prune symlinked/junction directories whose real target escapes root.
        kept_dirs: list[str] = []
        for dirname in dirnames:
            real_dir = os.path.realpath(os.path.join(dirpath, dirname))
            if _is_within(real_dir, base):
                kept_dirs.append(dirname)
        dirnames[:] = sorted(kept_dirs)

        budget_left = max_files - len(files)
        for filename in sorted(filenames):
            if budget_left <= 0:
                truncated_files = True
                break
            if allowed and not any(filename.lower().endswith(ext.lower()) for ext in allowed):
                continue
            full_path = os.path.join(dirpath, filename)
            if not _is_within(os.path.realpath(full_path), base):
                continue
            files.append(os.path.relpath(full_path, base).replace(os.sep, "/"))
            budget_left -= 1
        if truncated_files:
            break

    meta = {
        "exists": True,
        "dirs_scanned": dirs_scanned,
        "file_count": len(files),
        "scan_truncated": truncated_files or truncated_dirs,
    }
    return sorted(files), meta


def collect_project_files(root: str, relative_path: str = "", extensions: Any | None = None) -> list[str]:
    """Backward-compatible wrapper returning only the relative file list."""
    files, _ = collect_project_files_budgeted(root, relative_path, extensions)
    return files


def read_text_limited(path: str, limit: int) -> tuple[str, bool]:
    """Read at most ``limit`` characters directly from disk (no unbounded read)."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        chunk = handle.read(max(limit, 0) + 1)
    return chunk[:limit], len(chunk) > limit


def read_project_members(
    root: str,
    rel_paths: list[str],
    *,
    per_file_limit: int,
    total_limit: int = MAX_BATCH_TOTAL_CHARS,
    max_files: int = MAX_BATCH_FILES,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Read multiple workspace members under per-file and total char budgets."""
    contents: dict[str, str] = {}
    truncated_files: list[str] = []
    skipped: list[str] = []
    chars_read = 0
    file_count_truncated = len(rel_paths) > max_files
    total_budget_truncated = False

    for rel in rel_paths[:max_files]:
        full_path = resolve_member_path(root, rel)
        if not full_path or not os.path.isfile(full_path):
            skipped.append(rel)
            continue
        remaining = total_limit - chars_read
        if remaining <= 0:
            total_budget_truncated = True
            skipped.append(rel)
            continue
        text, truncated = read_text_limited(full_path, min(per_file_limit, remaining))
        contents[rel] = text
        chars_read += len(text)
        if truncated:
            truncated_files.append(rel)

    meta = {
        "files_requested": len(rel_paths),
        "files_read": len(contents),
        "files_skipped": skipped,
        "chars_read": chars_read,
        "per_file_limit": per_file_limit,
        "total_limit": total_limit,
        "truncated_files": truncated_files,
        "file_count_truncated": file_count_truncated,
        "total_budget_truncated": total_budget_truncated,
    }
    return contents, meta


def detect_common_issues(content: str, file_name: str) -> list[str]:
    """Detect common code issues and anti-patterns."""
    issues: list[str] = []
    lowered = content.lower()

    if "todo" in lowered or "fixme" in lowered:
        issues.append(f"{file_name}: contains TODO/FIXME markers that should be resolved or tracked.")
    if re.search(r"['\"](?:/tmp|/var|/etc|~|[A-Za-z]:\\)", content):
        issues.append(f"{file_name}: contains hardcoded filesystem paths which can break portability.")
    if "exec(" in lowered or "eval(" in lowered:
        issues.append(f"{file_name}: dynamic execution is risky and should be validated carefully.")
    if "subprocess" in lowered and "shell=True" in lowered:
        issues.append(f"{file_name}: subprocess call may be vulnerable to shell injection when shell=True is used.")
    if "print(" in lowered and "debug" in lowered:
        issues.append(f"{file_name}: debug logging may be left in production code.")
    if not issues:
        issues.append(f"{file_name}: no obvious issues detected in the inspected snippet.")
    return issues


def build_project_summary(files: list[str], project_root: str) -> dict[str, Any]:
    """Build a summary of project structure and file distribution."""
    ext_counts: dict[str, int] = {}
    for file_name in files:
        _, ext = os.path.splitext(file_name)
        ext = ext.lower() or "<no-extension>"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    summary_text = (
        f"Project root: {project_root}\n"
        f"Files inspected: {len(files)}\n"
        f"Extensions: {', '.join(f'{key}={value}' for key, value in sorted(ext_counts.items())) or 'none'}"
    )

    return {
        "project_root": project_root,
        "files": files,
        "counts_by_extension": ext_counts,
        "summary": summary_text,
    }


def build_code_review_report(files_by_path: dict[str, str]) -> dict[str, Any]:
    """Generate a comprehensive code review report."""
    review_items: list[str] = []
    issue_count = 0
    for file_path, content in files_by_path.items():
        issues = detect_common_issues(content, file_path)
        if issues:
            review_items.extend(issues)
            issue_count += len(issues)

    return {
        "review": "Code review finished in read-only mode.",
        "issues": review_items,
        "issue_count": issue_count,
    }


def build_error_fix_report(files_by_path: dict[str, str]) -> dict[str, Any]:
    """Generate error detection and fix suggestions."""
    fixes: list[str] = []
    for file_path, content in files_by_path.items():
        lowered = content.lower()
        if "todo" in lowered or "fixme" in lowered:
            fixes.append(f"{file_path}: replace stale TODO/FIXME markers with actionable tracked issues or remove them.")
        if re.search(r"['\"](?:/tmp|/var|/etc|~|[A-Za-z]:\\)", content):
            fixes.append(f"{file_path}: move filesystem paths to config or runtime input instead of hardcoded paths.")
        if "exec(" in lowered or "eval(" in lowered:
            fixes.append(f"{file_path}: avoid dynamic execution unless strictly necessary; prefer explicit APIs and validation.")
        if "shell=True" in lowered and "subprocess" in lowered:
            fixes.append(f"{file_path}: remove shell=True or sanitize parameters to reduce injection risk.")
    if not fixes:
        fixes.append("No urgent fix suggestions detected in the inspected files.")
    return {"fixes": fixes}


def build_multi_file_summary(files_by_path: dict[str, str]) -> dict[str, Any]:
    """Build a multi-file cross-cutting summary."""
    ordered_files = list(files_by_path.keys())
    total_chars = sum(len(content) for content in files_by_path.values())
    summary_text = (
        f"Project overview: {len(ordered_files)} files, {total_chars} chars inspected.\n"
        f"Primary files: {', '.join(ordered_files[:10])}"
    )
    return {
        "project": {
            "file_count": len(ordered_files),
            "total_chars": total_chars,
            "files": ordered_files,
        },
        "summary": summary_text,
    }


def build_quick_audit(
    files_by_path: dict[str, str],
    tone: str = "professional",
    *,
    include_review: bool = True,
    include_fixes: bool = True,
    include_structure: bool = True,
) -> dict[str, Any]:
    """Build a quick audit combining the analysis sections that are enabled."""
    content_parts: list[str] = []
    audit: dict[str, Any] = {}
    if include_review:
        review = build_code_review_report(files_by_path)
        audit["review"] = review
        content_parts.extend(["Review:", *review["issues"][:5]])
    if include_fixes:
        fixes = build_error_fix_report(files_by_path)
        audit["fixes"] = fixes
        content_parts.extend(["Fixes:", *fixes["fixes"][:5]])
    if include_structure:
        structure = build_multi_file_summary(files_by_path)
        audit["structure"] = structure
        content_parts.extend(["Structure:", structure["summary"]])
    audit["formatted"] = format_response("\n".join(content_parts), tone)
    return audit


def format_response(text: str, tone: str) -> str:
    """Format response with appropriate tone."""
    if tone == "catgirl":
        return f"喵~ meow~ nya~ {text}"
    return f"Professional review:\n{text}"


@neko_plugin
class DevelopmentAidePlugin(NekoPluginBase):
    """开发辅助型插件：导入 Skill、审查代码、分析结构并给出只读建议。"""

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.skill_path = ""
        self.workspace_root = ""
        self.read_only = True
        self.max_chars = DEFAULT_MAX_CHARS
        self.default_file_extensions = list(DEFAULT_EXTENSIONS)
        self.analysis_tone = "professional"
        self.enable_code_review = True
        self.enable_error_fix = True
        self.enable_project_summary = True
        self.enable_multi_file_summary = True

    # -- lifecycle ---------------------------------------------------------

    @lifecycle(id="startup")
    async def on_startup(self, **_) -> Ok | Err:
        """Initialize plugin on startup."""
        try:
            await self._reload_settings()
            return Ok({"status": "ready", "read_only": self.read_only})
        except Exception as e:
            return Err(SdkError(f"Startup failed: {str(e)}"))

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_) -> Ok | Err:
        """Clean up on shutdown."""
        return Ok({"status": "stopped"})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_) -> Ok | Err:
        """Reload settings when configuration changes."""
        try:
            await self._reload_settings()
            return Ok({"status": "reloaded", "read_only": self.read_only})
        except Exception as e:
            return Err(SdkError(f"Config reload failed: {str(e)}"))

    async def _reload_settings(self) -> None:
        """Load and apply plugin settings from persistent configuration."""
        cfg = await self.config.dump()
        settings = cfg.get("settings", {}) if isinstance(cfg, dict) else {}
        if not isinstance(settings, dict):
            settings = {}
        self.skill_path = str(settings.get("skill_path", self.skill_path) or "")
        self.workspace_root = str(settings.get("workspace_root", self.workspace_root) or "")
        self.read_only = bool(settings.get("read_only", self.read_only))
        try:
            self.max_chars = coerce_read_limit(settings.get("max_chars", self.max_chars))[0]
        except ValueError:
            self.max_chars = DEFAULT_MAX_CHARS
        self.analysis_tone = str(settings.get("analysis_tone", self.analysis_tone) or "professional")
        self.enable_code_review = bool(settings.get("enable_code_review", self.enable_code_review))
        self.enable_error_fix = bool(settings.get("enable_error_fix", self.enable_error_fix))
        self.enable_project_summary = bool(settings.get("enable_project_summary", self.enable_project_summary))
        self.enable_multi_file_summary = bool(
            settings.get("enable_multi_file_summary", self.enable_multi_file_summary)
        )
        extensions = settings.get("default_file_extensions", self.default_file_extensions)
        if isinstance(extensions, (list, tuple, set)) and extensions:
            self.default_file_extensions = sorted(_normalize_extensions(extensions))

    def _settings_payload(self) -> dict[str, Any]:
        return {
            "skill_path": self.skill_path,
            "workspace_root": self.workspace_root,
            "read_only": self.read_only,
            "max_chars": self.max_chars,
            "analysis_tone": self.analysis_tone,
            "enable_code_review": self.enable_code_review,
            "enable_error_fix": self.enable_error_fix,
            "enable_project_summary": self.enable_project_summary,
            "enable_multi_file_summary": self.enable_multi_file_summary,
            "default_file_extensions": list(self.default_file_extensions),
        }

    async def _persist_settings(self) -> None:
        """Persist the current settings so a config reload keeps them."""
        await self.config.set("settings", self._settings_payload())

    # -- guards ------------------------------------------------------------

    def _configured_root(self) -> str | None:
        """Return the resolved workspace root, or None when unset/missing."""
        root = resolve_scan_root(self.workspace_root)
        if root is None or not os.path.isdir(root):
            return None
        return root

    def _feature_enabled_error(self, attr: str, label: str) -> Err | None:
        if bool(getattr(self, attr, False)):
            return None
        return Err(SdkError(f"{label}功能已在设置中关闭，请在面板开启后再使用。"))

    async def _collect_workspace_files(
        self,
        relative_path: str,
        extensions: list[str] | None,
    ) -> tuple[str | None, list[str], dict[str, Any], Err | None]:
        root = self._configured_root()
        if root is None:
            if not str(self.workspace_root or "").strip():
                return None, [], {}, Err(SdkError("尚未配置工作区目录，请先在设置面板保存 workspace_root。"))
            return None, [], {}, Err(SdkError(f"工作区不存在或不是目录：{self.workspace_root}"))
        if ("\x00" in (relative_path or "")) or ((relative_path or "") and os.path.isabs(relative_path)):
            return None, [], {}, Err(SdkError("relative_path 必须是工作区内的相对路径，不允许绝对路径。"))
        if resolve_scan_root(root, relative_path) is None:
            return None, [], {}, Err(SdkError(f"扫描路径越出工作区，已拒绝：{relative_path}"))
        files, meta = await asyncio.to_thread(
            collect_project_files_budgeted,
            root,
            relative_path or "",
            extensions or self.default_file_extensions,
        )
        return root, files, meta, None

    # -- AI/tool entries ---------------------------------------------------

    @plugin_entry(
        id="import_skill",
        name="导入 Skill",
        description="导入一个 Skill 技能目录，并记入本插件的辅助能力列表。仅记录路径与可读取范围，不修改任何业务文件。",
        input_schema={
            "type": "object",
            "properties": {
                "skill_path": {"type": "string"},
                "skill_name": {"type": "string"},
            },
            "required": ["skill_path"],
        },
        llm_result_fields=["result", "skill_path", "message"],
    )
    async def import_skill(self, skill_path: str = "", skill_name: str = "", **_) -> Ok | Err:
        """Import a skill directory for enhanced capabilities."""
        if not skill_path:
            return Err(SdkError("必须提供 skill_path。"))
        abs_path = os.path.abspath(skill_path)
        if not os.path.isdir(abs_path):
            return Err(SdkError(f"Skill 路径不存在或不是目录：{abs_path}"))
        try:
            self.skill_path = abs_path
            self.read_only = True
            await self._persist_settings()
            return Ok({
                "result": "success",
                "skill_path": abs_path,
                "skill_name": skill_name or os.path.basename(abs_path),
                "message": "Skill 已导入，当前为只读访问模式。",
            })
        except Exception as e:
            return Err(SdkError(f"Failed to persist skill import: {str(e)}"))

    @plugin_entry(
        id="list_project_files",
        name="列出项目文件",
        description="只读列出工作区下的文件列表，供猫娘识别可以评估的源码和配置文件。遍历有文件数与目录数上限。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
            },
        },
        llm_result_fields=["result", "files", "count", "truncated"],
    )
    async def list_project_files(self, relative_path: str = "", extensions: list[str] | None = None, **_) -> Ok | Err:
        """List files in project directory with optional filtering."""
        root, files, meta, error = await self._collect_workspace_files(relative_path, extensions)
        if error is not None:
            return error
        return Ok({
            "result": "success",
            "files": files,
            "count": len(files),
            "root": root,
            "truncated": bool(meta.get("scan_truncated")),
            "dirs_scanned": meta.get("dirs_scanned", 0),
        })

    @plugin_entry(
        id="read_project_file",
        name="读取项目文件",
        description=(
            "只读指定文件内容，用于代码审阅、错误定位和陪伴式开发建议。"
            "⚠️ relative_path 必须是工作区内的相对路径；禁止绝对路径、../ 越界和指向工作区外的符号链接。"
            "读取按 max_chars 字符预算在磁盘层限量读取，禁止写入或修改文件。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 1},
            },
            "required": ["relative_path"],
        },
        llm_result_fields=["result", "path", "content", "truncated"],
    )
    async def read_project_file(self, relative_path: str = "", max_chars: int | None = None, **_) -> Ok | Err:
        """Read and return file content within a bounded per-file char limit."""
        if not relative_path:
            return Err(SdkError("relative_path 不能为空。"))
        try:
            limit, capped = coerce_read_limit(max_chars, self.max_chars)
        except ValueError as exc:
            return Err(SdkError(str(exc)))
        root = self._configured_root()
        if root is None:
            return Err(SdkError("尚未配置有效的工作区目录，请先在设置面板保存 workspace_root。"))
        full_path = resolve_member_path(root, relative_path)
        if not full_path or not os.path.isfile(full_path):
            return Err(SdkError(f"文件不存在、越出工作区或是指向外部的链接：{relative_path}"))
        try:
            content, truncated = await asyncio.to_thread(read_text_limited, full_path, limit)
            return Ok({
                "result": "success",
                "path": relative_path,
                "content": content,
                "truncated": truncated,
                "limit": limit,
                "limit_capped": capped,
                "read_only": self.read_only,
            })
        except OSError as exc:
            return Err(SdkError(f"Failed to read file: {str(exc)}"))

    @plugin_entry(
        id="code_review",
        name="代码审查入口",
        description="按只读方式审查当前项目或指定目录的代码，并给出潜在问题、质量提示和关注点。受功能开关 enable_code_review 控制。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
        },
        llm_result_fields=["result", "report"],
    )
    async def code_review(
        self,
        relative_path: str = "",
        extensions: list[str] | None = None,
        tone: str = "professional",
        **_,
    ) -> Ok | Err:
        """Perform comprehensive code review with bounded file reads."""
        gate = self._feature_enabled_error("enable_code_review", "代码审查")
        if gate is not None:
            return gate
        root, files, scan_meta, error = await self._collect_workspace_files(relative_path, extensions)
        if error is not None:
            return error
        if not files:
            return Err(SdkError("没有找到可审查的代码文件。"))
        limit = coerce_read_limit(None, self.max_chars)[0]
        inferred_files, read_meta = await asyncio.to_thread(
            read_project_members,
            root,
            files,
            per_file_limit=limit,
            total_limit=MAX_BATCH_TOTAL_CHARS,
            max_files=MAX_BATCH_FILES,
        )
        if not inferred_files:
            return Err(SdkError("候选文件均不可读或已越出工作区。"))
        report = build_code_review_report(inferred_files)
        report["formatted"] = format_response("\n".join(report["issues"]), tone or self.analysis_tone)
        report["budget"] = {"scan": scan_meta, "read": read_meta}
        return Ok({"result": "success", "report": report})

    @plugin_entry(
        id="error_fix",
        name="错误定位与修复建议",
        description="定位常见错误并给出修复建议，适合用于调试、问题排查和重构前评审。受功能开关 enable_error_fix 控制。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
        },
        llm_result_fields=["result", "fixes"],
    )
    async def error_fix(
        self,
        relative_path: str = "",
        extensions: list[str] | None = None,
        tone: str = "professional",
        **_,
    ) -> Ok | Err:
        """Detect and suggest fixes for common errors."""
        gate = self._feature_enabled_error("enable_error_fix", "错误定位与修复建议")
        if gate is not None:
            return gate
        root, files, scan_meta, error = await self._collect_workspace_files(relative_path, extensions)
        if error is not None:
            return error
        if not files:
            return Err(SdkError("没有找到可检查的文件。"))
        limit = coerce_read_limit(None, self.max_chars)[0]
        inferred_files, read_meta = await asyncio.to_thread(
            read_project_members,
            root,
            files,
            per_file_limit=limit,
            total_limit=MAX_BATCH_TOTAL_CHARS,
            max_files=MAX_BATCH_FILES,
        )
        if not inferred_files:
            return Err(SdkError("候选文件均不可读或已越出工作区。"))
        fixes = build_error_fix_report(inferred_files)
        fixes["formatted"] = format_response("\n".join(fixes["fixes"]), tone or self.analysis_tone)
        fixes["budget"] = {"scan": scan_meta, "read": read_meta}
        return Ok({"result": "success", "fixes": fixes})

    @plugin_entry(
        id="project_summary",
        name="项目结构分析摘要",
        description="快速生成项目结构概览，并总结文件分布、扩展名统计和总体工程状态。受功能开关 enable_project_summary 控制。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
        },
        llm_result_fields=["result", "summary"],
    )
    async def project_summary(
        self,
        relative_path: str = "",
        extensions: list[str] | None = None,
        tone: str = "professional",
        **_,
    ) -> Ok | Err:
        """Generate project structure summary."""
        gate = self._feature_enabled_error("enable_project_summary", "项目结构分析摘要")
        if gate is not None:
            return gate
        root, files, scan_meta, error = await self._collect_workspace_files(relative_path, extensions)
        if error is not None:
            return error
        if not files:
            return Err(SdkError("没有找到可分析的项目文件。"))
        summary = build_project_summary(files, root)
        summary["formatted"] = format_response(summary["summary"], tone or self.analysis_tone)
        summary["budget"] = {"scan": scan_meta}
        return Ok({"result": "success", "summary": summary})

    @plugin_entry(
        id="multi_file_summary",
        name="读取多文件后汇总建议",
        description="汇总多个文件内容，形成跨文件的总览、热点和建议。受功能开关 enable_multi_file_summary 控制，读取有文件数与总字符预算。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
        },
        llm_result_fields=["result", "summary"],
    )
    async def multi_file_summary(
        self,
        relative_path: str = "",
        extensions: list[str] | None = None,
        tone: str = "professional",
        **_,
    ) -> Ok | Err:
        """Summarize insights across multiple files."""
        gate = self._feature_enabled_error("enable_multi_file_summary", "多文件汇总")
        if gate is not None:
            return gate
        root, files, scan_meta, error = await self._collect_workspace_files(relative_path, extensions)
        if error is not None:
            return error
        if not files:
            return Err(SdkError("没有找到可汇总的文件。"))
        limit = coerce_read_limit(None, self.max_chars)[0]
        selected_files, read_meta = await asyncio.to_thread(
            read_project_members,
            root,
            files,
            per_file_limit=limit,
            total_limit=MAX_BATCH_TOTAL_CHARS,
            max_files=12,
        )
        if not selected_files:
            return Err(SdkError("候选文件均不可读或已越出工作区。"))
        summary = build_multi_file_summary(selected_files)
        summary["formatted"] = format_response(summary["summary"], tone or self.analysis_tone)
        summary["budget"] = {"scan": scan_meta, "read": read_meta}
        return Ok({"result": "success", "summary": summary})

    @plugin_entry(
        id="quick_audit",
        name="一键开发审查",
        description=(
            "一次性执行审查、修复建议和结构摘要，生成一份总览式开发建议。"
            "复合操作只执行设置中已启用的功能；全部关闭时拒绝执行。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
        },
        llm_result_fields=["result", "audit"],
    )
    @ui.action(id="quick_audit", label="一键开发审查", tone="primary", refresh_context=True)
    async def quick_audit(
        self,
        relative_path: str = "",
        extensions: list[str] | None = None,
        tone: str = "professional",
        **_,
    ) -> Ok | Err:
        """Execute comprehensive quick audit combining enabled analyses."""
        include_review = self.enable_code_review
        include_fixes = self.enable_error_fix
        include_structure = self.enable_multi_file_summary
        if not (include_review or include_fixes or include_structure):
            return Err(SdkError("代码审查、修复建议与多文件汇总功能均已关闭，无法执行一键开发审查。"))
        root, files, scan_meta, error = await self._collect_workspace_files(relative_path, extensions)
        if error is not None:
            return error
        if not files:
            return Err(SdkError("没有找到可审查的文件。"))
        limit = coerce_read_limit(None, self.max_chars)[0]
        selected_files, read_meta = await asyncio.to_thread(
            read_project_members,
            root,
            files,
            per_file_limit=limit,
            total_limit=MAX_BATCH_TOTAL_CHARS,
            max_files=12,
        )
        if not selected_files:
            return Err(SdkError("候选文件均不可读或已越出工作区。"))
        audit = build_quick_audit(
            selected_files,
            tone=tone or self.analysis_tone,
            include_review=include_review,
            include_fixes=include_fixes,
            include_structure=include_structure,
        )
        audit["budget"] = {"scan": scan_meta, "read": read_meta}
        return Ok({"result": "success", "audit": audit})

    # -- UI actions (must carry BOTH @plugin_entry and @ui.action, #2) -----

    @plugin_entry(
        id="save_settings",
        name="保存设置",
        description="保存 Development-Aide 面板设置（工作区、读取上限、语气、功能开关），并持久化到插件配置，重载后不丢失。",
        input_schema={
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "skill_path": {"type": "string"},
                        "workspace_root": {"type": "string"},
                        "read_only": {"type": "boolean"},
                        "max_chars": {"type": "integer", "minimum": 1},
                        "analysis_tone": {"type": "string", "enum": ["professional", "catgirl"]},
                        "enable_code_review": {"type": "boolean"},
                        "enable_error_fix": {"type": "boolean"},
                        "enable_project_summary": {"type": "boolean"},
                        "enable_multi_file_summary": {"type": "boolean"},
                    },
                },
            },
            "required": ["config"],
        },
        llm_result_fields=["status", "config"],
    )
    @ui.action(
        id="save_settings",
        label=tr("actions.save.label", default="保存设置"),
        tone="primary",
        refresh_context=True,
    )
    async def save_settings(self, config: dict | None = None, **_) -> Ok | Err:
        """Validate, apply and persist plugin configuration."""
        if not isinstance(config, dict):
            return Err(SdkError("config 必须是对象。"))
        try:
            workspace_root = str(config.get("workspace_root", self.workspace_root) or "").strip()
            if workspace_root and not os.path.isabs(workspace_root):
                return Err(SdkError("workspace_root 必须是绝对路径。"))
            try:
                max_chars, capped = coerce_read_limit(config.get("max_chars", self.max_chars))
            except ValueError as exc:
                return Err(SdkError(str(exc)))
            analysis_tone = str(config.get("analysis_tone", self.analysis_tone) or "professional")
            if analysis_tone not in {"professional", "catgirl"}:
                return Err(SdkError("analysis_tone 只能是 professional 或 catgirl。"))

            self.skill_path = str(config.get("skill_path", self.skill_path) or "").strip()
            self.workspace_root = workspace_root
            self.read_only = bool(config.get("read_only", self.read_only))
            self.max_chars = max_chars
            self.analysis_tone = analysis_tone
            self.enable_code_review = bool(config.get("enable_code_review", self.enable_code_review))
            self.enable_error_fix = bool(config.get("enable_error_fix", self.enable_error_fix))
            self.enable_project_summary = bool(config.get("enable_project_summary", self.enable_project_summary))
            self.enable_multi_file_summary = bool(
                config.get("enable_multi_file_summary", self.enable_multi_file_summary)
            )
            await self._persist_settings()
            return Ok({
                "status": "saved",
                "config": self._settings_payload(),
                "workspace_exists": bool(workspace_root) and os.path.isdir(workspace_root),
                "max_chars_capped": capped,
            })
        except Exception as e:
            return Err(SdkError(f"Failed to save settings: {str(e)}"))

    @plugin_entry(
        id="generate_code_review",
        name="生成代码审查",
        description="面板按钮：在当前工作区执行代码审查。受 enable_code_review 开关控制。",
        input_schema={"type": "object", "properties": {}},
        llm_result_fields=["result", "report"],
    )
    @ui.action(id="generate_code_review", label="代码审查", tone="info", refresh_context=True)
    async def generate_code_review_action(self, **_) -> Ok | Err:
        """UI action for code review."""
        return await self.code_review(tone=self.analysis_tone)

    @plugin_entry(
        id="generate_error_fix",
        name="生成修复建议",
        description="面板按钮：在当前工作区执行错误定位与修复建议。受 enable_error_fix 开关控制。",
        input_schema={"type": "object", "properties": {}},
        llm_result_fields=["result", "fixes"],
    )
    @ui.action(id="generate_error_fix", label="修复建议", tone="warning", refresh_context=True)
    async def generate_error_fix_action(self, **_) -> Ok | Err:
        """UI action for error fix suggestions."""
        return await self.error_fix(tone=self.analysis_tone)

    @plugin_entry(
        id="generate_project_summary",
        name="生成结构摘要",
        description="面板按钮：在当前工作区生成项目结构摘要。受 enable_project_summary 开关控制。",
        input_schema={"type": "object", "properties": {}},
        llm_result_fields=["result", "summary"],
    )
    @ui.action(id="generate_project_summary", label="结构摘要", tone="primary", refresh_context=True)
    async def generate_project_summary_action(self, **_) -> Ok | Err:
        """UI action for project summary."""
        return await self.project_summary(tone=self.analysis_tone)

    @plugin_entry(
        id="generate_multi_file_summary",
        name="生成多文件汇总",
        description="面板按钮：在当前工作区生成多文件汇总。受 enable_multi_file_summary 开关控制。",
        input_schema={"type": "object", "properties": {}},
        llm_result_fields=["result", "summary"],
    )
    @ui.action(id="generate_multi_file_summary", label="多文件汇总", tone="success", refresh_context=True)
    async def generate_multi_file_summary_action(self, **_) -> Ok | Err:
        """UI action for multi-file summary."""
        return await self.multi_file_summary(tone=self.analysis_tone)

    @ui.context(id="settings")
    async def settings_context(self) -> dict[str, Any]:
        """Provide settings context for UI."""
        return {
            "config": self._settings_payload(),
            "status": {
                "ready": True,
                "mode": self.analysis_tone,
                "skill_loaded": bool(self.skill_path) and os.path.isdir(self.skill_path),
                "workspace_configured": bool(str(self.workspace_root or "").strip()),
                "workspace_exists": self._configured_root() is not None,
                "features_enabled": {
                    "code_review": self.enable_code_review,
                    "error_fix": self.enable_error_fix,
                    "project_summary": self.enable_project_summary,
                    "multi_file_summary": self.enable_multi_file_summary,
                },
            },
        }
