import pytest

from registry.issue import parse_issue

BODY = """### 插件来源

tenko-plugin-demo

### 分类

娱乐

### 标签（可选）

工具, 娱乐

### 图标（可选）

![icon](https://github.com/user-attachments/assets/abc-123)

### 确认

- [x] 我确认我是该项目的所有者或维护者
"""


def test_parse_filled_form():
    assert parse_issue(BODY) == {
        "source": "tenko-plugin-demo",
        "category": "娱乐",
        "tags": "工具,娱乐",
        "icon": "https://github.com/user-attachments/assets/abc-123",
    }


def test_empty_optional_fields_and_unchecked_confirmation():
    empty = BODY.replace("工具, 娱乐", "_No response_").replace("![icon](https://github.com/user-attachments/assets/abc-123)", "_No response_")
    assert parse_issue(empty)["tags"] == "" and parse_issue(empty)["icon"] == ""
    with pytest.raises(ValueError):
        parse_issue(BODY.replace("[x]", "[ ]"))


def test_category_accepts_label_or_id_and_lists_choices(root):
    from registry.submission import Rejected, resolve_category

    assert resolve_category("娱乐", root) == resolve_category("fun", root) == "fun"
    with pytest.raises(Rejected, match="其他（other）"):
        resolve_category("", root)
