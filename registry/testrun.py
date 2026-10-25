"""`test` 与 `retest`：在隔离虚拟环境里安装真实宿主和插件，并加载一遍。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from . import net
from .discover import tenko_api_specifier
from .model import (
    DIST_PREFIX,
    ROOT,
    load_plugin,
    normalize_dist,
    now_iso,
    plugin_files,
    save_plugin,
)

MAX_DIST_BYTES = 16 * 1024 * 1024
DEFAULT_PYTHON = "3.12"
PROBE = Path(__file__).with_name("probe.py")
INSTALL_TIMEOUT = 1200
PROBE_TIMEOUT = 300
# 刚发布的版本：发现用的 PyPI JSON 接口已经有了，uv 用的简单索引还要等几分钟 CDN 刷新
INDEX_ATTEMPTS = 6
INDEX_WAIT = 30


class InfraError(RuntimeError):
    """测试环境本身出了问题（网络、宿主安装失败等），不能据此判断插件好坏。"""


@dataclass
class Outcome:
    errors: list[str] = field(default_factory=list)
    probe: dict[str, Any] = field(default_factory=dict)
    host: dict[str, str] | None = None  # {tenko, api, python}

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def requires_api(self) -> str | None:
        return tenko_api_specifier(self.probe.get("requires_dist"))


def clean_env() -> dict[str, str]:
    """子进程会执行第三方插件代码，不把令牌类环境变量传给它。"""

    marks = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")
    return {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in marks)}


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=clean_env(), stdin=subprocess.DEVNULL
    )


def _tail(proc: subprocess.CompletedProcess[str], lines: int = 15) -> str:
    return "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-lines:])


def _not_on_index(proc: subprocess.CompletedProcess[str], spec: str) -> bool:
    return f"no version of {spec.lower()}" in (proc.stderr or "").lower()


def plugin_spec(source: dict[str, Any], version: dict[str, Any]) -> str:
    if source["type"] == "pypi":
        return f"{source['package']}=={version['version']}"
    spec = f"git+{source['url']}@{version['pin']['commit']}"
    if source.get("subdirectory"):
        spec += f"#subdirectory={source['subdirectory']}"
    return spec


def host_specs(tenko_ref: str | None, tenko_path: Path | None) -> list[str]:
    if tenko_path:
        return [str(tenko_path), str(tenko_path / "packages" / "tenko-api")]
    url = f"git+{net.TENKO_REPO}@{tenko_ref}"
    return [f"tenko @ {url}", f"tenko-api @ {url}#subdirectory=packages/tenko-api"]


_FREEZE = (
    "import importlib.metadata as m;"
    "print('\\n'.join(sorted(f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions())))"
)


def run_test(
    source: dict[str, Any],
    version: dict[str, Any],
    *,
    plugin_id: str | None,
    tenko_ref: str | None = None,
    tenko_path: Path | None = None,
    python: str = DEFAULT_PYTHON,
    runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = run_cmd,
    sleep: Callable[[float], None] = time.sleep,
) -> Outcome:
    outcome = Outcome()
    with tempfile.TemporaryDirectory(prefix="tenko-registry-") as tmp:
        work = Path(tmp)
        venv_python = str(work / "venv" / "bin" / "python")

        def step(cmd: list[str], timeout: int, what: str) -> subprocess.CompletedProcess[str]:
            try:
                return runner(cmd, timeout)
            except (subprocess.SubprocessError, OSError) as error:
                raise InfraError(f"{what}: {error}") from error

        proc = step(["uv", "venv", "--python", python, str(work / "venv")], 120, "创建虚拟环境")
        if proc.returncode:
            raise InfraError(f"创建虚拟环境失败:\n{_tail(proc)}")
        install = ["uv", "pip", "install", "--python", venv_python]
        proc = step([*install, *host_specs(tenko_ref, tenko_path)], INSTALL_TIMEOUT, "安装宿主")
        if proc.returncode:
            hint = "\n（该 Tenko 版本不含 packages/tenko-api，尚不支持第三方插件）" if "no subdirectory" in proc.stderr else ""
            raise InfraError(f"安装 Tenko 宿主失败:\n{_tail(proc)}{hint}")

        # 把宿主装好的全部依赖作为约束：插件与宿主冲突时安装失败，而不是悄悄改掉宿主。
        frozen = step([venv_python, "-I", "-c", _FREEZE], 60, "读取宿主依赖")
        constraints = work / "constraints.txt"
        constraints.write_text(frozen.stdout, encoding="utf-8")

        spec = plugin_spec(source, version)
        cmd = [*install, "-c", str(constraints), spec]
        if source["type"] == "pypi":
            cmd += ["--refresh-package", source["package"]]
        for attempt in range(INDEX_ATTEMPTS):
            proc = step(cmd, INSTALL_TIMEOUT, "安装插件")
            if not (proc.returncode and _not_on_index(proc, spec)):
                break
            if attempt + 1 < INDEX_ATTEMPTS:
                sleep(INDEX_WAIT)
        else:
            # 不算插件的错：留着不写测试结果，下一轮 --untested 会再测
            raise InfraError(f"PyPI 索引里还查不到 {spec}，下一轮再测")
        out = work / "probe.json"
        if proc.returncode:
            outcome.errors.append(f"插件安装失败:\n{_tail(proc)}")
            outcome.host = _host_versions(constraints, python)
            return outcome

        cmd = [venv_python, "-I", str(PROBE), "--root", str(work / "host"), "--out", str(out)]
        (work / "host").mkdir()
        if source["type"] == "pypi":
            cmd += ["--dist", source["package"]]
        if plugin_id:
            cmd += ["--id", plugin_id]
        try:
            proc = step(cmd, PROBE_TIMEOUT, "运行探针")
        except InfraError as error:
            outcome.errors.append(str(error))
            proc = None
        if not out.is_file():
            outcome.errors.append(f"探针没有产出结果:\n{_tail(proc) if proc else ''}")
            outcome.host = _host_versions(constraints, python)
            return outcome
        outcome.probe = json.loads(out.read_text(encoding="utf-8"))

    probe = outcome.probe
    outcome.errors += probe["errors"]
    outcome.host = {k: probe[k] for k in ("tenko", "api", "python") if k in probe}
    if "dist" in probe:
        _check_dist(outcome, source)
    return outcome


def _host_versions(constraints: Path, python: str) -> dict[str, str]:
    pins = dict(line.split("==", 1) for line in constraints.read_text().split())
    return {"tenko": pins.get("tenko", "unknown"), "api": pins.get("tenko-api", "unknown"), "python": python}


def _check_dist(outcome: Outcome, source: dict[str, Any]) -> None:
    probe = outcome.probe
    if not normalize_dist(probe["dist"]).startswith(DIST_PREFIX):
        outcome.errors.append(f"分发包名必须以 {DIST_PREFIX} 开头，实际为 {probe['dist']}")
    if outcome.requires_api is None:
        outcome.errors.append("插件没有声明对 tenko-api 的依赖")
    if not probe.get("requires_python"):
        outcome.errors.append("插件没有声明 requires-python")
    if probe["size"] > MAX_DIST_BYTES:
        outcome.errors.append(f"安装体积 {probe['size'] / 2**20:.1f} MB，超过 16 MB 上限")


def apply_outcome(version: dict[str, Any], outcome: Outcome, at: str | None = None) -> None:
    """把测试结果写进版本项。宿主版本未知（环境没搭起来）时不改动。"""

    if outcome.host is None:
        return
    version["tested"] = {**outcome.host, "at": at or now_iso()}
    version["valid"] = outcome.ok
    if outcome.ok:
        # git 版本在这里第一次知道自己的兼容声明；pypi 版本通常 discover 时已有。
        version["requires_api"] = version.get("requires_api") or outcome.requires_api
        version["requires_python"] = version.get("requires_python") or outcome.probe["requires_python"]


def outside_api_range(version: dict[str, Any], outcome: Outcome) -> bool:
    """测试宿主的 tenko-api 不在该版本声明的范围内：这是不兼容，不是插件坏了。"""

    spec, api = version.get("requires_api"), (outcome.host or {}).get("api")
    if not spec or not api or api == "unknown":
        return False
    try:
        return not SpecifierSet(spec).contains(api, prereleases=True)
    except InvalidSpecifier:
        return False


def pick_version(entry: dict[str, Any], wanted: str | None) -> dict[str, Any]:
    if not entry["versions"]:
        raise ValueError("该插件还没有任何版本，请先运行 discover")
    if wanted is None:
        return entry["versions"][0]
    for item in entry["versions"]:
        if item["version"] == wanted:
            return item
    raise ValueError(f"找不到版本 {wanted}")


def format_outcome(plugin_id: str, version: str, outcome: Outcome) -> str:
    if outcome.ok:
        host = outcome.host or {}
        return f"通过  {plugin_id} {version}（Tenko {host.get('tenko')}，tenko-api {host.get('api')}）"
    return f"未通过  {plugin_id} {version}\n" + "\n".join(f"  - {e}" for e in outcome.errors)


def retest(
    root: Path = ROOT,
    *,
    count: int = 3,
    tenko_ref: str | None = None,
    plugin_id: str | None = None,
    untested: bool = False,
    **kwargs: Any,
) -> tuple[list[str], list[str]]:
    """对每个插件最新的 count 个未撤回版本重新测试，返回 (结果行, 环境错误)。

    ``untested`` 只测其中还没测过的版本：每小时跑一次，让新版本尽快能装，又不刷新旧结果。
    """

    ref = tenko_ref or net.latest_tenko_tag()
    lines: list[str] = [f"测试宿主: Tenko {ref}"]
    infra: list[str] = []
    paths = [root / "plugins" / f"{plugin_id}.json"] if plugin_id else plugin_files(root)
    for path in paths:
        entry = load_plugin(path.stem, root)
        fresh = [v for v in entry["versions"] if v["yanked"] is None][:count]
        if untested:
            fresh = [v for v in fresh if v["tested"] is None]
        if not fresh:
            continue
        for item in fresh:
            try:
                outcome = run_test(entry["source"], item, plugin_id=path.stem, tenko_ref=ref, **kwargs)
            except InfraError as error:
                infra.append(f"{path.stem} {item['version']}: {error}")
                continue
            if outside_api_range(item, outcome):
                # 宿主升级 tenko-api 后旧版本、或领先于宿主的新版本都会走到这里，保留上次结果。
                lines.append(
                    f"跳过  {path.stem} {item['version']}：要求 tenko-api {item['requires_api']}，"
                    f"测试宿主是 {outcome.host['api']}"
                )
                continue
            apply_outcome(item, outcome)
            lines.append(format_outcome(path.stem, item["version"], outcome))
        save_plugin(path.stem, entry, root)
    return lines, infra
