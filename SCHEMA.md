# index.json 规范（schema v1）

`index.json` 是插件目录的唯一产物，由 `python -m registry build` 从本仓库的数据生成，
发布在：

- GitHub Pages（`gh-pages` 分支）：`https://g1331.github.io/tenko-registry/index.json`
- jsDelivr 镜像：`https://cdn.jsdelivr.net/gh/g1331/tenko-registry@gh-pages/index.json`

## 兼容规则

- 客户端必须忽略不认识的字段；新增字段不会提高 `schema_version`。
- 只有删除字段、改变字段含义或类型时才提高 `schema_version`。客户端遇到更高的主版本应拒绝使用并提示升级。
- 路径类字段（`icon`）相对 `index.json` 所在位置解析。

## 结构

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-10-21T00:00:00Z",
  "categories": {"manage": "群管理", "tool": "实用工具", "other": "其他"},
  "plugins": {
    "example": {
      "name": "示例插件",
      "description": "不超过 80 个字符",
      "authors": [{"name": "you", "github": "you"}],
      "homepage": "https://github.com/you/tenko-plugin-example",
      "license": "MIT",
      "category": "tool",
      "tags": ["翻译"],
      "tier": "listed",
      "icon": "icons/example-3f9a1c2e.png",
      "source": {"type": "pypi", "package": "tenko-plugin-example"},
      "versions": [
        {
          "version": "0.1.0",
          "pin": {"sha256": ["<该发布的所有文件哈希>"]},
          "requires_api": ">=0.2,<1",
          "requires_python": ">=3.11,<3.14",
          "published_at": "2026-10-01T08:00:00Z",
          "tested": {"tenko": "4.0.0", "api": "0.2.0", "python": "3.12", "at": "2026-10-21T00:00:00Z"},
          "valid": true,
          "yanked": null
        }
      ]
    }
  },
  "blocked": {
    "bad-plugin": {"reason": "…", "since": "2026-10-01T00:00:00Z", "dists": ["tenko-plugin-bad"]}
  }
}
```

`plugins/<id>.json` 的内容就是 `plugins[id]` 的形状（文件名即插件 ID，不在文件内重复）。
`generated_at` 在每次 build 时写入，UTC，格式 `YYYY-MM-DDTHH:MM:SSZ`；所有时间字段都用这个格式。

## 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | 整数 | 固定为 `1` |
| `generated_at` | 字符串 | 生成时间。每天会重新发布一次，所以客户端可以用它判断目录是否过期 |
| `categories` | 对象 | 分类 ID 到显示名，按 `categories.txt` 的顺序；客户端按这个顺序展示分类筛选 |
| `plugins` | 对象 | 键是插件 ID，按字母序排列 |
| `blocked` | 对象 | 屏蔽名单，见下文 |

## 插件条目

插件 ID 等于该包在 `tenko.plugins` 入口组中的入口名，必须匹配 `^[a-z][a-z0-9_]*$`，
不能与 `builtin_ids.txt` 中的 Tenko 内置插件重名，也不能与已有条目重复。

| 字段 | 类型 | 来源 | 说明 |
| --- | --- | --- | --- |
| `name` | 字符串 | `plugin.metadata` 的 `name` | 显示名称 |
| `description` | 字符串 | `plugin.metadata` 的 `description` | 1 到 80 个字符 |
| `authors` | 列表 | `plugin.metadata` 的 `author` | 每项 `{name, github}`；`github` 在作者名与提交者用户名一致时填写，否则为 `null`；元数据没有作者时用提交者 |
| `homepage` | 字符串 | 包的项目链接（Homepage、Source、Repository），都没有时用 GitHub 仓库地址 | https 地址 |
| `license` | 字符串 | 包的 `license`（SPDX 表达式） | 必须在 `licenses.txt` 允许列表内，写入时使用规范大小写 |
| `category` | 字符串 | 提交者在 issue 中选择，维护者可调整 | 必须是 `categories` 里的一个 ID；用于分类筛选 |
| `tags` | 字符串列表 | 提交者在 issue 中填写 | 最多 5 个，每个 1 到 16 个字符；可以为空。只用于搜索，不作为筛选项 |
| `tier` | 字符串 | 维护者 | `official`（Tenko 官方维护）或 `listed`（社区收录）；新收录一律为 `listed` |
| `icon` | 字符串或缺省 | 图标流程产出 | 相对路径 `icons/<id>-<sha256 前 8 位>.png`；没有图标时省略（本仓库数据文件里为 `null`） |
| `source` | 对象 | 提交者在 issue 中填写 | 见下文 |
| `versions` | 列表 | CI | 按版本号从新到旧排列，同一版本号只出现一次；预发布版本也包含，是否采用由客户端决定 |

### source

- PyPI：`{"type": "pypi", "package": "tenko-plugin-example"}`，包名必须以 `tenko-plugin-` 开头。
- git：`{"type": "git", "url": "https://github.com/you/repo", "subdirectory": null}`；
  `subdirectory` 用于插件位于仓库子目录的情形。

### versions[]

| 字段 | 类型 | 来源 | 说明 |
| --- | --- | --- | --- |
| `version` | 字符串 | PyPI 版本号，或去掉前导 `v` 的 git 标签 | PEP 440 版本号 |
| `pin` | 对象 | CI | PyPI：`{"sha256": [...]}`，该发布全部文件的哈希；git：`{"commit": "<40 位十六进制>", "tag": "v0.1.0"}` |
| `requires_api` | 字符串或 `null` | 包元数据 `Requires-Dist` 中的 `tenko-api` 范围 | PyPI 版本由 discover 填写；**git 版本在首次测试之前为 `null`**，测试通过后由已安装包的元数据填写 |
| `requires_python` | 字符串或 `null` | 包元数据 `Requires-Python` | 同上；git 版本首次测试前为 `null` |
| `published_at` | 字符串或 `null` | PyPI 上最早的文件上传时间 | git 版本为 `null`（发现标签时不克隆仓库） |
| `tested` | 对象或 `null` | CI 的 `test` / `retest` | `{tenko, api, python, at}`：最近一次测试所用的宿主版本、`tenko-api` 版本、Python 次版本和时间；从未测试为 `null` |
| `valid` | 布尔 | CI | 最近一次测试是否通过。为 `true` 时 `tested`、`requires_api`、`requires_python` 一定有值 |
| `yanked` | 对象或 `null` | PyPI 撤回信息，或维护者手动设置 | `{reason, since}`；`since` 是本仓库发现撤回的时间，不是 PyPI 上的撤回时间 |

`valid` 的含义是：在 `tested` 记录的宿主上，该版本能按 Tenko 的方式安装并加载（见下文“测试”）。
它不代表代码经过审查，也不保证在别的宿主版本上可用，兼容性请结合 `requires_api` 判断。

撤回（`yanked`）只会被 CI 设置，不会被 CI 清除：PyPI 上取消撤回后，需要维护者手动删掉该字段。

## 屏蔽名单

```json
"blocked": {"bad-plugin": {"reason": "…", "since": "2026-10-01T00:00:00Z", "dists": ["tenko-plugin-bad"]}}
```

键通常就是插件 ID，也允许用连字符（`^[a-z][a-z0-9_-]*$`），因为被屏蔽的对象可能从未收录。
`dists` 列出被屏蔽的分发包名（均以 `tenko-plugin-` 开头）。客户端应按分发包名匹配已安装的插件，
并拒绝安装或加载命中的包。被屏蔽的 ID 和分发包不能同时出现在 `plugins` 里。

## 图标

`icon` 指向经过处理的 PNG：128×128、RGBA、不含任何元数据，文件名 `<id>-<内容 sha256 前 8 位>.png`。
文件名带哈希，所以可以长期缓存，更换图标会产生新的 URL，旧文件在同一次提交里删除。

输入要求（`python -m registry icon` 和收录检查共用）：

- 格式只接受 PNG、WebP，按文件内容识别；JPEG、SVG 和动图（动态 WebP、APNG）一律拒绝；
- 裁剪缩放后必须有透明像素，完全不透明的图标会被拒绝（菜单会把图标染成白色显示）；
- 输入文件不超过 1 MB，短边不小于 64 px；
- 地址只接受 https，下载时按流限制大小并设置超时；
- 非正方形图片居中裁切后缩放。

## 测试

`test` 在一次性虚拟环境里安装 Tenko 宿主（默认取 `g1331/tenko` 最新的 `v*` 标签，以及同一标签下
`packages/tenko-api` 的源码）和指定版本的插件，再用宿主的 `PluginRuntime` 加载。通过需要同时满足：

- 插件安装成功。宿主已装好的依赖被当作约束，插件与宿主冲突时安装失败，不会改动宿主；
- 恰有一个 `tenko.plugins` 入口指向该分发包，入口名就是插件 ID；
- 插件被成功加载，其 `tenko-api` 范围包含宿主提供的版本；
- 分发包名以 `tenko-plugin-` 开头，依赖 `tenko-api`，声明了 `requires-python`；
- 安装后的文件总大小不超过 16 MB。

安装与加载过程中读到的 `plugin.metadata`（名称、描述、作者、图标地址）用于生成收录条目。
