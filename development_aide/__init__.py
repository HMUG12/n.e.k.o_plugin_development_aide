from __future__ import annotations

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
        pass

    class Err(dict):
        pass

    class NekoPluginBase:
        def __init__(self, ctx: Any = None):
            self.ctx = ctx
            self.config = type("ConfigProxy", (), {"dump": lambda self, *args, **kwargs: {"settings": {}}})()
            self.logger = type("Logger", (), {"exception": lambda self, *args, **kwargs: None})()

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


def _normalize_extensions(extensions: Any | None) -> set[str]:
    if not extensions:
        return {".py", ".ts", ".tsx", ".md", ".toml", ".json"}
    normalized: set[str] = set()
    for ext in extensions:
        value = str(ext).strip()
        if not value:
            continue
        normalized.add(value if value.startswith(".") else f".{value}")
    return normalized or {".py", ".ts", ".tsx", ".md", ".toml", ".json"}


def collect_project_files(root: str, relative_path: str = "", extensions: Any | None = None) -> list[str]:
    base_root = os.path.abspath(root)
    scan_root = os.path.join(base_root, relative_path) if relative_path else base_root
    if not os.path.isdir(scan_root):
        return []

    allowed = _normalize_extensions(extensions)
    files: list[str] = []
    for dirpath, _, filenames in os.walk(scan_root):
        for filename in sorted(filenames):
            full_path = os.path.join(dirpath, filename)
            if allowed and not any(filename.lower().endswith(ext.lower()) for ext in allowed):
                continue
            rel_path = os.path.relpath(full_path, base_root).replace(os.sep, "/")
            files.append(rel_path)
    return sorted(files)


def detect_common_issues(content: str, file_name: str) -> list[str]:
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
    review_items: list[str] = []
    issue_count = 0
    for file_path, content in files_by_path.items():
        issues = detect_common_issues(content, file_path)
        if issues:
            review_items.extend(issues)
            issue_count += len(issues)

    report = {
        "review": "Code review finished in read-only mode.",
        "issues": review_items,
        "issue_count": issue_count,
    }
    return report


def build_error_fix_report(files_by_path: dict[str, str]) -> dict[str, Any]:
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


def build_quick_audit(files_by_path: dict[str, str], tone: str = "professional") -> dict[str, Any]:
    review = build_code_review_report(files_by_path)
    fixes = build_error_fix_report(files_by_path)
    structure = build_multi_file_summary(files_by_path)
    content_parts = [
        "Review:",
        *[issue for issue in review["issues"][:5]],
        "Fixes:",
        *[fix for fix in fixes["fixes"][:5]],
        "Structure:",
        structure["summary"],
    ]
    return {
        "review": review,
        "fixes": fixes,
        "structure": structure,
        "formatted": format_response("\n".join(content_parts), tone),
    }


def format_response(text: str, tone: str) -> str:
    if tone == "catgirl":
        return f"喵~ meow~ nya~ {text}"
    return f"Professional review:\n{text}"


@neko_plugin
class DevelopmentAidePlugin(NekoPluginBase):
    """开发辅助型插件：导入 Skill、审查代码、分析结构并给出只读建议。"""

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.skill_path = "/home/codespace/.trae/skills/neko-plugin-dev"
        self.workspace_root = "/workspaces/n.e.k.o_plugin_Development-Aide"
        self.read_only = True
        self.max_chars = 4000
        self.default_file_extensions = [".py", ".ts", ".tsx", ".md", ".toml", ".json"]
        self.analysis_tone = "professional"
        self.enable_code_review = True
        self.enable_error_fix = True
        self.enable_project_summary = True
        self.enable_multi_file_summary = True

    @lifecycle(id="startup")
    async def on_startup(self, **_) -> Ok | Err:
        await self._reload_settings()
        return Ok({"status": "ready", "read_only": self.read_only})

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_) -> Ok | Err:
        return Ok({"status": "stopped"})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_) -> Ok | Err:
        await self._reload_settings()
        return Ok({"status": "reloaded", "read_only": self.read_only})

    async def _reload_settings(self) -> None:
        cfg = await self.config.dump()
        settings = cfg.get("settings", {})
        self.skill_path = settings.get("skill_path", self.skill_path)
        self.workspace_root = settings.get("workspace_root", self.workspace_root)
        self.read_only = bool(settings.get("read_only", self.read_only))
        self.max_chars = int(settings.get("max_chars", self.max_chars))
        self.analysis_tone = settings.get("analysis_tone", self.analysis_tone)
        self.enable_code_review = bool(settings.get("enable_code_review", self.enable_code_review))
        self.enable_error_fix = bool(settings.get("enable_error_fix", self.enable_error_fix))
        self.enable_project_summary = bool(settings.get("enable_project_summary", self.enable_project_summary))
        self.enable_multi_file_summary = bool(settings.get("enable_multi_file_summary", self.enable_multi_file_summary))
        self.default_file_extensions = settings.get("default_file_extensions", self.default_file_extensions)

    def _normalize_root(self, root: str) -> str:
        if not root:
            return self.workspace_root
        return os.path.abspath(root)

    def _safe_file_path(self, relative_path: str, root: str | None = None) -> str | None:
        base_root = self._normalize_root(root or self.workspace_root)
        abs_path = os.path.abspath(os.path.join(base_root, relative_path))
        root_prefix = os.path.abspath(base_root)
        if abs_path != root_prefix and not abs_path.startswith(root_prefix + os.sep):
            return None
        return abs_path

    def _collect_from_root(self, relative_path: str = "", extensions: list[str] | None = None) -> list[str]:
        base_root = self._normalize_root(self.workspace_root)
        scan_root = os.path.join(base_root, relative_path) if relative_path else base_root
        return collect_project_files(base_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)

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
        if not skill_path:
            return Err(SdkError("必须提供 skill_path。"))
        abs_path = os.path.abspath(skill_path)
        if not os.path.isdir(abs_path):
            return Err(SdkError(f"Skill 路径不存在或不是目录：{abs_path}"))
        self.skill_path = abs_path
        self.read_only = True
        return Ok({
            "result": "success",
            "skill_path": abs_path,
            "skill_name": skill_name or os.path.basename(abs_path),
            "message": "Skill 已导入，当前为只读访问模式。",
        })

    @plugin_entry(
        id="list_project_files",
        name="列出项目文件",
        description="只读列出工作区下的文件列表，供猫娘识别可以评估的源码和配置文件。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
        llm_result_fields=["result", "files"],
    )
    async def list_project_files(self, relative_path: str = "", extensions: list[str] | None = None, **_) -> Ok | Err:
        base_root = self._normalize_root(self.workspace_root)
        scan_root = os.path.join(base_root, relative_path) if relative_path else base_root
        if not os.path.isdir(scan_root):
            return Err(SdkError(f"目录不存在：{scan_root}"))
        files = collect_project_files(base_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)
        return Ok({"result": "success", "files": files[:200], "count": len(files[:200]), "root": base_root})

    @plugin_entry(
        id="read_project_file",
        name="读取项目文件",
        description="只读指定文件内容，用于代码审阅、错误定位和陪伴式开发建议。禁止写入或修改文件。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["relative_path"],
        },
        llm_result_fields=["result", "path", "content", "truncated"],
    )
    async def read_project_file(self, relative_path: str = "", max_chars: int | None = None, **_) -> Ok | Err:
        if not relative_path:
            return Err(SdkError("relative_path 不能为空。"))
        full_path = self._safe_file_path(relative_path)
        if not full_path or not os.path.isfile(full_path):
            return Err(SdkError(f"文件不存在或不在允许的工作区范围内：{relative_path}"))
        with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        limit = int(max_chars or self.max_chars)
        truncated = len(content) > limit
        snippet = content[:limit]
        return Ok({"result": "success", "path": relative_path, "content": snippet, "truncated": truncated, "read_only": self.read_only})

    @plugin_entry(
        id="code_review",
        name="代码审查入口",
        description="按只读方式审查当前项目或指定目录的代码，并给出潜在问题、质量提示和关注点。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
            "required": [],
        },
        llm_result_fields=["result", "report"],
    )
    async def code_review(self, relative_path: str = "", extensions: list[str] | None = None, tone: str = "professional", **_) -> Ok | Err:
        files = collect_project_files(self.workspace_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)
        if not files:
            return Err(SdkError("没有找到可审查的代码文件。"))
        inferred_files = {name: open(os.path.join(self.workspace_root, name), "r", encoding="utf-8", errors="replace").read() for name in files[:25]}
        report = build_code_review_report(inferred_files)
        report["formatted"] = format_response("\n".join(report["issues"]), tone or self.analysis_tone)
        return Ok({"result": "success", "report": report})

    @plugin_entry(
        id="error_fix",
        name="错误定位与修复建议",
        description="定位常见错误并给出修复建议，适合用于调试、问题排查和重构前评审。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
            "required": [],
        },
        llm_result_fields=["result", "fixes"],
    )
    async def error_fix(self, relative_path: str = "", extensions: list[str] | None = None, tone: str = "professional", **_) -> Ok | Err:
        files = collect_project_files(self.workspace_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)
        if not files:
            return Err(SdkError("没有找到可检查的文件。"))
        inferred_files = {name: open(os.path.join(self.workspace_root, name), "r", encoding="utf-8", errors="replace").read() for name in files[:25]}
        fixes = build_error_fix_report(inferred_files)
        fixes["formatted"] = format_response("\n".join(fixes["fixes"]), tone or self.analysis_tone)
        return Ok({"result": "success", "fixes": fixes})

    @plugin_entry(
        id="project_summary",
        name="项目结构分析摘要",
        description="快速生成项目结构概览，并总结文件分布、扩展名统计和总体工程状态。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
            "required": [],
        },
        llm_result_fields=["result", "summary"],
    )
    async def project_summary(self, relative_path: str = "", extensions: list[str] | None = None, tone: str = "professional", **_) -> Ok | Err:
        files = collect_project_files(self.workspace_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)
        if not files:
            return Err(SdkError("没有找到可分析的项目文件。"))
        summary = build_project_summary(files, self.workspace_root)
        summary["formatted"] = format_response(summary["summary"], tone or self.analysis_tone)
        return Ok({"result": "success", "summary": summary})

    @plugin_entry(
        id="multi_file_summary",
        name="读取多文件后汇总建议",
        description="汇总多个文件内容，形成跨文件的总览、热点和建议，适合用于文档梳理和开发规划。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
            "required": [],
        },
        llm_result_fields=["result", "summary"],
    )
    async def multi_file_summary(self, relative_path: str = "", extensions: list[str] | None = None, tone: str = "professional", **_) -> Ok | Err:
        files = collect_project_files(self.workspace_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)
        if not files:
            return Err(SdkError("没有找到可汇总的文件。"))
        selected_files = {}
        for file_name in files[:12]:
            full_path = os.path.join(self.workspace_root, file_name)
            with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
                selected_files[file_name] = handle.read()
        summary = build_multi_file_summary(selected_files)
        summary["formatted"] = format_response(summary["summary"], tone or self.analysis_tone)
        return Ok({"result": "success", "summary": summary})

    @plugin_entry(
        id="quick_audit",
        name="一键开发审查",
        description="一次性执行审查、修复建议和结构摘要，生成一份总览式开发建议。",
        input_schema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "tone": {"type": "string", "enum": ["professional", "catgirl"]},
            },
            "required": [],
        },
        llm_result_fields=["result", "audit"],
    )
    async def quick_audit(self, relative_path: str = "", extensions: list[str] | None = None, tone: str = "professional", **_) -> Ok | Err:
        files = collect_project_files(self.workspace_root, relative_path=relative_path, extensions=extensions or self.default_file_extensions)
        if not files:
            return Err(SdkError("没有找到可审查的文件。"))
        selected_files = {}
        for file_name in files[:12]:
            full_path = os.path.join(self.workspace_root, file_name)
            with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
                selected_files[file_name] = handle.read()
        audit = build_quick_audit(selected_files, tone=tone or self.analysis_tone)
        return Ok({"result": "success", "audit": audit})

    @ui.action(
        label=tr("actions.save.label", default="保存设置"),
        tone="primary",
        refresh_context=True,
    )
    async def save_settings(self, config: dict | None = None, **_) -> Ok | Err:
        if not isinstance(config, dict):
            return Err(SdkError("config 必须是对象。"))
        self.skill_path = str(config.get("skill_path", self.skill_path))
        self.workspace_root = str(config.get("workspace_root", self.workspace_root))
        self.read_only = bool(config.get("read_only", self.read_only))
        self.max_chars = int(config.get("max_chars", self.max_chars))
        self.analysis_tone = str(config.get("analysis_tone", self.analysis_tone))
        self.enable_code_review = bool(config.get("enable_code_review", self.enable_code_review))
        self.enable_error_fix = bool(config.get("enable_error_fix", self.enable_error_fix))
        self.enable_project_summary = bool(config.get("enable_project_summary", self.enable_project_summary))
        self.enable_multi_file_summary = bool(config.get("enable_multi_file_summary", self.enable_multi_file_summary))
        return Ok({"status": "saved", "skill_path": self.skill_path, "workspace_root": self.workspace_root, "read_only": self.read_only, "analysis_tone": self.analysis_tone})

    @ui.action(id="generate_code_review", label="代码审查", tone="info")
    async def generate_code_review_action(self, **_) -> Ok | Err:
        return await self.code_review(tone=self.analysis_tone)

    @ui.action(id="generate_error_fix", label="修复建议", tone="warning")
    async def generate_error_fix_action(self, **_) -> Ok | Err:
        return await self.error_fix(tone=self.analysis_tone)

    @ui.action(id="generate_project_summary", label="结构摘要", tone="primary")
    async def generate_project_summary_action(self, **_) -> Ok | Err:
        return await self.project_summary(tone=self.analysis_tone)

    @ui.action(id="generate_multi_file_summary", label="多文件汇总", tone="success")
    async def generate_multi_file_summary_action(self, **_) -> Ok | Err:
        return await self.multi_file_summary(tone=self.analysis_tone)

    @ui.context(id="settings")
    async def settings_context(self):
        return {
            "config": {
                "skill_path": self.skill_path,
                "workspace_root": self.workspace_root,
                "read_only": self.read_only,
                "max_chars": self.max_chars,
                "analysis_tone": self.analysis_tone,
                "enable_code_review": self.enable_code_review,
                "enable_error_fix": self.enable_error_fix,
                "enable_project_summary": self.enable_project_summary,
                "enable_multi_file_summary": self.enable_multi_file_summary,
            },
            "status": {
                "ready": True,
                "mode": self.analysis_tone,
                "skill_loaded": os.path.isdir(self.skill_path),
                "features_enabled": {
                    "code_review": self.enable_code_review,
                    "error_fix": self.enable_error_fix,
                    "project_summary": self.enable_project_summary,
                    "multi_file_summary": self.enable_multi_file_summary,
                },
            },
        }
