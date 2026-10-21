"""`check-submission`：校验一次收录申请，通过后生成 plugins/<id>.json，并产出中文报告。"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression

from . import net, testrun
from .build import load_all, source_key
from .discover import discover_entry
from .icon import IconError, install_icon, load_source, process_icon
from .model import (
    DIST_PREFIX,
    GITHUB_REPO,
    MAX_DESCRIPTION,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    PLUGIN_ID,
    ROOT,
    builtin_ids,
    normalize_dist,
    read_json,
    save_plugin,
    validate_plugin,
)

PYPI_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
PUSH_ROLES = {"admin", "maintain", "write"}


class Rejected(Exception):
    """某项检查未通过；消息就是报告里的原因。"""


@dataclass
class Deps:
    """所有外部依赖，测试时整体替换。"""

    get_json: Callable[..., Any] = net.get_json
    fetch_bytes: Callable[[str, int], bytes] = net.fetch_bytes
    ls_tags: Callable[[str], dict[str, str]] = net.git_ls_remote_tags
    run_test: Callable[..., testrun.Outcome] = testrun.run_test


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failure: str | None = None
    summary: list[str] = field(default_factory=list)
    plugin_id: str | None = None

    def markdown(self) -> str:
        head = "## 收录检查未通过" if self.failure else "## 收录检查通过"
        lines = [head, "", *(f"- [x] {item}" for item in self.passed)]
        if self.failure:
            lines += [f"- [ ] {self.failure.splitlines()[0]}"]
            lines += [f"  {line}" for line in self.failure.splitlines()[1:]]
            lines += ["", "请根据上面的原因修改后，编辑这个 issue 即可重新检查。"]
        lines += [f"- 注意: {note}" for note in self.notes]
        if self.summary:
            lines += ["", *self.summary]
        if not self.failure:
            lines += ["", "已生成收录条目，将自动创建合并请求，维护者审核后合并。"]
        return "\n".join(lines) + "\n"


def parse_source(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("https://"):
        url, _, tag = text.rpartition("@")
        match = GITHUB_REPO.fullmatch(url) if url else None
        if not match or not tag:
            raise Rejected("GitHub 来源的格式应为 `https://github.com/<用户>/<仓库>@<标签>`")
        return {"type": "git", "url": f"https://github.com/{match[1]}/{match[2]}", "subdirectory": None, "tag": tag}
    if not PYPI_NAME.fullmatch(text):
        raise Rejected("来源应是 PyPI 包名，或 `https://github.com/<用户>/<仓库>@<标签>`")
    if not normalize_dist(text).startswith(DIST_PREFIX):
        raise Rejected(f"PyPI 包名必须以 `{DIST_PREFIX}` 开头，当前为 `{text}`")
    return {"type": "pypi", "package": text}


def github_repo_of(source: dict[str, Any], deps: Deps) -> tuple[str, str]:
    """GitHub 来源直接取仓库；PyPI 来源要求项目链接指向一个 GitHub 仓库。"""

    if source["type"] == "git":
        match = GITHUB_REPO.fullmatch(source["url"])
        return match[1], match[2]
    info = deps.get_json(f"https://pypi.org/pypi/{source['package']}/json")["info"]
    urls = [*(info.get("project_urls") or {}).values(), info.get("home_page") or ""]
    for url in urls:
        match = GITHUB_REPO.fullmatch(url.strip()) if isinstance(url, str) else None
        if match:
            return match[1], match[2]
    raise Rejected("PyPI 项目的链接（project.urls）中没有 GitHub 仓库地址，无法确认归属")


def check_ownership(owner: str, repo: str, submitter: str, token: str | None, deps: Deps) -> None:
    if not LOGIN.fullmatch(submitter):
        raise Rejected(f"提交者用户名无效: {submitter!r}")
    if owner.lower() == submitter.lower():
        return
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        data = deps.get_json(
            f"https://api.github.com/repos/{owner}/{repo}/collaborators/{submitter}/permission",
            headers,
        )
        role = data.get("role_name") or data.get("permission")
    except net.NetError:
        role = None  # 无权查询协作者时 GitHub 返回 403/404，一律按未通过处理
    if role not in PUSH_ROLES:
        raise Rejected(
            f"无法确认 @{submitter} 是 {owner}/{repo} 的所有者或有推送权限的协作者。"
            f"请用仓库所有者账号提交，或在维护者协助下人工审核"
        )


def check_license(probe: dict[str, Any], root: Path) -> str:
    raw = probe.get("license") or (probe.get("metadata") or {}).get("license")
    if not isinstance(raw, str) or "\n" in raw or len(raw) > 100:
        raise Rejected("没有读到 SPDX 许可证表达式。请在 pyproject.toml 中写 `license = \"MIT\"` 这样的 SPDX 标识符")
    try:
        expression = canonicalize_license_expression(raw)
    except InvalidLicenseExpression:
        raise Rejected(f"许可证 `{raw}` 不是合法的 SPDX 表达式") from None
    allowed = {
        line.strip() for line in (root / "licenses.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    ids = re.findall(r"[A-Za-z0-9.+-]+", re.sub(r" WITH [^ ()]+", "", expression))
    bad = [i for i in ids if i not in allowed and i not in ("AND", "OR")]
    if bad:
        raise Rejected(f"许可证 `{', '.join(bad)}` 不在允许收录的列表（licenses.txt）内")
    return expression


def author_name(author: Any) -> str:
    name = author.get("name") if isinstance(author, dict) else author
    return re.sub(r"\s*<.*>$", "", str(name or "")).strip()


def derive_entry(
    source: dict[str, Any], probe: dict[str, Any], license_id: str, submitter: str, repo_url: str,
    tags: list[str],
) -> dict[str, Any]:
    meta = probe["metadata"]
    names = [n for n in map(author_name, meta.get("author") or []) if n] or [submitter]
    urls = {k.lower(): v for k, v in {**probe.get("project_urls", {}), **(meta.get("urls") or {})}.items()}
    homepage = next(
        (urls[k] for k in ("homepage", "source", "repository") if str(urls.get(k, "")).startswith("https://")),
        repo_url,
    )
    return {
        "name": meta["name"],
        "description": meta["description"].strip(),
        "authors": [{"name": n, "github": submitter if n.lower() == submitter.lower() else None} for n in names],
        "homepage": homepage,
        "license": license_id,
        "tags": tags,
        "tier": "listed",
        "icon": None,
        "source": {k: v for k, v in source.items() if k != "tag"},
        "versions": [],
    }


def check_submission(
    source_text: str,
    submitter: str,
    *,
    tags: list[str] | None = None,
    icon: str | None = None,
    root: Path = ROOT,
    deps: Deps | None = None,
    token: str | None = None,
    **test_kwargs: Any,
) -> Report:
    deps = deps or Deps()
    report = Report()
    tags = tags or []
    try:
        _run(report, source_text, submitter, tags, icon, root, deps, token or os.environ.get("GITHUB_TOKEN"), test_kwargs)
    except Rejected as error:
        report.failure = str(error)
    except net.NetError as error:
        report.failure = f"访问外部服务失败，请稍后编辑 issue 重试: {error}"
    except testrun.InfraError as error:
        report.failure = f"测试环境出错（不代表插件有问题），请稍后重试:\n{error}"
    return report


def _run(report, source_text, submitter, tags, icon, root, deps, token, test_kwargs) -> None:
    source = parse_source(source_text)
    report.passed.append(f"来源格式与命名: `{source_text.strip()}`")

    if len(tags) > MAX_TAGS or any(not 0 < len(t) <= MAX_TAG_LENGTH for t in tags):
        raise Rejected(f"标签最多 {MAX_TAGS} 个，每个 1 到 {MAX_TAG_LENGTH} 个字符")

    plugins, blocked = load_all(root)
    key = source_key({"source": source})
    if any(source_key(e) == key for e in plugins.values()):
        raise Rejected("这个来源已经收录")
    blocked_dists = {normalize_dist(d) for b in blocked.values() for d in b["dists"]}
    if source["type"] == "pypi" and normalize_dist(source["package"]) in blocked_dists:
        raise Rejected("这个分发包在屏蔽名单中")

    owner, repo = github_repo_of(source, deps)
    check_ownership(owner, repo, submitter, token, deps)
    report.passed.append(f"归属: @{submitter} 对 {owner}/{repo} 有所有权或推送权限")

    skeleton = {"source": {k: v for k, v in source.items() if k != "tag"}, "versions": []}
    discover_entry(skeleton, get_json=deps.get_json, ls_tags=deps.ls_tags)
    versions = skeleton["versions"]
    if source["type"] == "git":
        version = next((v for v in versions if v["pin"]["tag"] == source["tag"]), None)
        if version is None:
            raise Rejected(f"仓库里没有形如 `vX.Y.Z` 的标签 `{source['tag']}`")
    else:
        version = next((v for v in versions if v["yanked"] is None), None)
        if version is None:
            raise Rejected("PyPI 上没有可用的（未撤回的）版本")

    outcome = deps.run_test(skeleton["source"], version, plugin_id=None, **test_kwargs)
    if not outcome.ok:
        raise Rejected("安装与加载测试未通过:\n" + "\n".join(f"- {e}" for e in outcome.errors))
    probe = outcome.probe
    host = outcome.host
    report.passed.append(
        f"安装与加载测试: {version['version']}（Tenko {host['tenko']}，tenko-api {host['api']}，Python {host['python']}）"
    )

    plugin_id = probe["id"]
    if not PLUGIN_ID.fullmatch(plugin_id):
        raise Rejected(f"插件 ID `{plugin_id}` 必须匹配 `^[a-z][a-z0-9_]*$`")
    if plugin_id in builtin_ids(root):
        raise Rejected(f"插件 ID `{plugin_id}` 与 Tenko 内置插件冲突")
    if plugin_id in plugins or plugin_id in blocked:
        raise Rejected(f"插件 ID `{plugin_id}` 已被占用")
    if normalize_dist(probe["dist"]) in blocked_dists:
        raise Rejected(f"分发包 `{probe['dist']}` 在屏蔽名单中")
    report.passed.append(f"插件 ID: `{plugin_id}`")

    license_id = check_license(probe, root)
    report.passed.append(f"许可证: {license_id}")

    meta = probe["metadata"]
    description = (meta.get("description") or "").strip()
    if not meta.get("name") or not description:
        raise Rejected("`plugin.metadata` 必须提供 `name` 和 `description`")
    if len(description) > MAX_DESCRIPTION:
        raise Rejected(f"`description` 不能超过 {MAX_DESCRIPTION} 个字符，当前 {len(description)} 个")

    entry = derive_entry(
        source, probe, license_id, submitter, f"https://github.com/{owner}/{repo}", tags
    )
    png = _icon_bytes(report, icon, meta.get("icon"), deps)
    entry["versions"] = versions
    testrun.apply_outcome(version, outcome)
    if png:
        entry["icon"] = install_icon(plugin_id, png, root)
    if errors := validate_plugin(plugin_id, entry, root):
        raise Rejected("生成的条目未通过校验:\n" + "\n".join(f"- {e}" for e in errors))
    save_plugin(plugin_id, entry, root)
    report.plugin_id = plugin_id
    report.summary = [
        "| 字段 | 值 |", "| --- | --- |",
        f"| 名称 | {entry['name']} |", f"| 简介 | {entry['description']} |",
        f"| 作者 | {', '.join(a['name'] for a in entry['authors'])} |",
        f"| 主页 | {entry['homepage']} |", f"| 标签 | {', '.join(tags) or '（无）'} |",
        f"| 图标 | {'已处理' if png else '无'} |", f"| 收录版本数 | {len(versions)}（仅 {version['version']} 经过测试） |",
    ]


def _icon_bytes(report: Report, explicit: str | None, from_meta: str | None, deps: Deps) -> bytes | None:
    """显式给出的图标必须合格；元数据里的图标不合格只提醒，不阻止收录。"""

    try:
        if explicit:
            if not explicit.startswith("https://"):
                raise IconError("图标地址必须是 https")
            return process_icon(load_source(explicit, deps.fetch_bytes))
        if from_meta and from_meta.startswith("https://"):
            return process_icon(load_source(from_meta, deps.fetch_bytes))
    except (IconError, net.NetError) as error:
        if explicit:
            raise Rejected(f"图标不符合要求: {error}") from error
        report.notes.append(f"`plugin.metadata` 中的图标没有采用（{error}），收录时不带图标，可稍后补充")
    return None
