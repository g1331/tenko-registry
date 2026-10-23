"""解析 .github/ISSUE_TEMPLATE/submit.yml 渲染出的 issue 正文。"""

from __future__ import annotations

import re

# 与 submit.yml 里各字段的 label 前缀保持一致。
FIELDS = {"source": "插件来源", "category": "分类", "tags": "标签", "icon": "图标", "confirm": "确认"}
URL = re.compile(r"https://[^\s)\"'>\]]+")


def parse_issue(body: str) -> dict[str, str]:
    """返回 {source, category, tags, icon}；tags 为逗号分隔，缺省字段为空串。"""

    sections: dict[str, str] = {}
    for part in re.split(r"^### +", body.replace("\r\n", "\n"), flags=re.M)[1:]:
        title, _, content = part.partition("\n")
        sections[title.strip()] = content.strip()

    def field(key: str) -> str:
        text = next((v for k, v in sections.items() if k.startswith(FIELDS[key])), "")
        return "" if text == "_No response_" else text

    if "[x]" not in field("confirm").lower():
        raise ValueError("请勾选“我确认拥有该项目”后再提交")
    source = field("source")
    if not source or "\n" in source:
        raise ValueError("请在“插件来源”中填写一个 PyPI 包名或 GitHub 地址@标签")
    tags = [t for t in re.split(r"[,，、\s]+", field("tags")) if t]
    icon_match = URL.search(field("icon"))
    return {"source": source, "category": field("category"), "tags": ",".join(tags), "icon": icon_match[0] if icon_match else ""}
