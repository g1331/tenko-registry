"""命令行入口：python -m registry <命令>。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import net
from .build import ValidationError, build
from .discover import discover
from .icon import IconError, set_icon
from .issue import parse_issue
from .model import load_plugin, save_plugin
from .submission import check_submission
from .testrun import DEFAULT_PYTHON, InfraError, apply_outcome, format_outcome, pick_version, retest, run_test


def cmd_build(args: argparse.Namespace) -> int:
    index = build(Path(args.out))
    print(f"已生成 {Path(args.out) / 'index.json'}：{len(index['plugins'])} 个插件，{len(index['blocked'])} 条屏蔽")
    return 0


def cmd_icon(args: argparse.Namespace) -> int:
    print(f"已更新 {set_icon(args.id, args.source)}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    changed, errors = discover(args.id)
    for plugin_id, changes in changed.items():
        for line in changes:
            print(f"{plugin_id}: {line}")
    for plugin_id, error in errors.items():
        print(f"{plugin_id}: 失败 - {error}", file=sys.stderr)
    return 1 if errors else 0


def _host_args(args: argparse.Namespace) -> dict:
    return {
        "tenko_ref": None if args.tenko_path else (args.tenko_ref or net.latest_tenko_tag()),
        "tenko_path": Path(args.tenko_path).resolve() if args.tenko_path else None,
        "python": args.python,
    }


def cmd_test(args: argparse.Namespace) -> int:
    entry = load_plugin(args.id)
    version = pick_version(entry, args.version)
    outcome = run_test(entry["source"], version, plugin_id=args.id, **_host_args(args))
    apply_outcome(version, outcome)
    save_plugin(args.id, entry)
    print(format_outcome(args.id, version["version"], outcome))
    return 0 if outcome.ok else 1


def cmd_check_submission(args: argparse.Namespace) -> int:
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    report = check_submission(
        args.source, args.submitter, category=args.category or "", tags=tags, icon=args.icon or None,
        **_host_args(args),
    )
    print(report.markdown())
    return 1 if report.failure else 0


def cmd_retest(args: argparse.Namespace) -> int:
    kwargs = _host_args(args)
    lines, infra = retest(**kwargs)
    print("\n".join(lines))
    for line in infra:
        print(f"环境错误 {line}", file=sys.stderr)
    return 1 if infra else 0


def cmd_parse_issue(args: argparse.Namespace) -> int:
    try:
        fields = parse_issue(sys.stdin.read())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    for key, value in fields.items():
        print(f"{key}={value}")
    return 0


def add_host_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tenko-ref", help="Tenko 的 git 标签，默认取 g1331/tenko 最新的 v* 标签")
    parser.add_argument("--tenko-path", help="本地 Tenko 仓库路径，用它代替 git 标签（调试用）")
    parser.add_argument("--python", default=DEFAULT_PYTHON, help=f"测试用的 Python 版本，默认 {DEFAULT_PYTHON}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m registry", description="Tenko 插件目录工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="校验数据并生成 index.json")
    p.add_argument("--out", default="dist")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("icon", help="处理并设置插件图标")
    p.add_argument("id")
    p.add_argument("source", help="本地文件或 https 地址")
    p.set_defaults(func=cmd_icon)

    p = sub.add_parser("discover", help="发现新版本")
    p.add_argument("--id")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("test", help="在隔离环境里安装并加载某个版本")
    p.add_argument("id")
    p.add_argument("--version")
    add_host_options(p)
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("check-submission", help="检查一次收录申请，输出 Markdown 报告")
    p.add_argument("--source", required=True, help="PyPI 包名，或 https://github.com/<用户>/<仓库>@<标签>")
    p.add_argument("--submitter", required=True, help="提交者的 GitHub 用户名")
    p.add_argument("--category", help="分类 ID 或显示名，见 categories.txt")
    p.add_argument("--tags", help="逗号分隔的标签")
    p.add_argument("--icon", help="图标的 https 地址")
    add_host_options(p)
    p.set_defaults(func=cmd_check_submission)

    p = sub.add_parser("retest", help="用最新 Tenko 重测每个插件最新的 3 个版本")
    add_host_options(p)
    p.set_defaults(func=cmd_retest)

    p = sub.add_parser("parse-issue", help="从标准输入读取 issue 正文，输出 key=value 行")
    p.set_defaults(func=cmd_parse_issue)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValidationError, IconError, InfraError, net.NetError, ValueError, FileNotFoundError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1
