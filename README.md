# tenko-registry

[Tenko](https://github.com/g1331/tenko) 的插件目录。Tenko 机器人下载这里发布的 `index.json`，
据此知道有哪些第三方插件、哪些版本通过了测试、哪些已被屏蔽。完整的数据规范见 [SCHEMA.md](SCHEMA.md)。

- GitHub Pages：`https://g1331.github.io/tenko-registry/index.json`
- jsDelivr 镜像：`https://cdn.jsdelivr.net/gh/g1331/tenko-registry@gh-pages/index.json`

## 给插件作者：如何收录

你只需要照 Tenko 的[示例插件](https://github.com/g1331/tenko/tree/main/examples/tenko-plugin-example)
写一个正常的包，然后填一张 issue 表单。

1. 分发包名以 `tenko-plugin-` 开头；在 `pyproject.toml` 的 `tenko.plugins` 入口组里声明插件，
   入口名就是插件 ID（`^[a-z][a-z0-9_]*$`，不能与 Tenko 内置插件或已收录插件重名，内置 ID 见 `builtin_ids.txt`）。
2. 依赖 `tenko-api` 并写明兼容范围，`pyproject.toml` 里写 `requires-python` 和 SPDX 格式的 `license`
   （必须在 [licenses.txt](licenses.txt) 的允许列表内）。
3. 用 `plugin.metadata(...)` 提供 `name` 和 `description`（不超过 80 个字符），可选 `author`、`icon`。
4. 发布到 PyPI，或给 GitHub 仓库打 `vX.Y.Z` 标签。
5. 到[提交插件](https://github.com/g1331/tenko-registry/issues/new?template=submit.yml)填写来源：
   PyPI 包名，或 `https://github.com/你/仓库@v0.1.0`，并选一个[分类](#分类)。标签和图标可选。

你必须是 GitHub 仓库的所有者，或有推送权限的协作者（PyPI 来源要求项目链接里有指向该仓库的地址）。
机器人会在 issue 下回复检查报告；没通过时按原因修改后编辑 issue 即可重新检查，通过后会自动开一个合并请求，
维护者审核合并，index.json 随即更新。

### 哪些信息是自动得到的

名称、简介、作者、主页、许可证来自你的包；版本号、文件哈希、发布时间、`tenko-api` 与 Python 兼容范围由 CI
从 PyPI 或 git 标签读取，之后每天自动发现新版本并重新测试。你发布新版本不需要再提交任何东西。
每个字段的来源见 SCHEMA.md。

CI 的测试会安装你的插件并用真实的 Tenko 宿主加载它，所以插件必须能在没有额外配置的情况下被加载
（缺少必填配置会导致加载失败）。

### 分类

每个插件属于一个分类，插件市场按分类筛选。标签只参与搜索，可以写具体的词（如游戏名、站点名）。

| ID | 显示名 | 收什么 |
| --- | --- | --- |
| `manage` | 群管理 | 入群审核、违禁词、禁言、清理、群数据统计 |
| `ai` | AI 对话 | 大模型聊天、AI 绘图、语音合成 |
| `fun` | 娱乐 | 群内小游戏、签到、抽签、复读等互动 |
| `gametool` | 游戏查询 | 查外部游戏的数据：战绩、服务器、角色、活动 |
| `feed` | 资讯订阅 | 动态推送、直播提醒、RSS、新闻 |
| `image` | 图片表情 | 表情包生成、图片处理、搜图 |
| `tool` | 实用工具 | 天气、翻译、提醒、计算等小工具 |
| `library` | 开发支持 | 给其他插件用的库或服务，以及示例插件 |
| `other` | 其他 | 放不进上面任何一类的 |

拿不准就选“其他”，维护者审核时会调整。新增分类请开 PR 修改 `categories.txt` 和上表。

### 图标要求

- 格式：透明背景的 PNG 或 WebP，不支持 JPEG、SVG 和动图；
- 内容：单色图形（比如一个剪影或符号），不要带底色。Tenko 的图片菜单会把图标统一染成白色，放进同一种底座里显示，不透明的方图会变成白块，因此会被拒绝；
- 文件不超过 1 MB，短边不小于 64 px，最好是正方形；
- 地址必须是 https，可以是 issue 里直接上传的图片，也可以是 `plugin.metadata(icon=...)` 里的地址。

系统会居中裁成正方形，缩放为 128×128 的 PNG，并去掉所有元数据，保存为 `icons/<id>-<哈希>.png`。
issue 里显式给出的图标不合格会拒绝收录；`plugin.metadata` 里的图标不合格只会被忽略。
之后想换图标，可以直接开 PR（运行 `python -m registry icon <id> <地址>` 即可生成文件），或联系维护者。

## 给维护者

### 目录结构

| 路径 | 内容 |
| --- | --- |
| `plugins/<id>.json` | 每个插件一个条目，`versions` 由 CI 维护 |
| `blocked.json` | 屏蔽名单 `{"<id>": {reason, since, dists}}` |
| `removed.json` | 下架记录 `[{id, reason, at}]`，只做历史，不进入 index.json |
| `icons/` | 处理后的图标 |
| `builtin_ids.txt`、`licenses.txt` | 保留的内置插件 ID、允许的许可证 |
| `categories.txt` | 分类，每行 `<ID> <显示名>`，顺序即展示顺序 |
| `registry/` | CLI，`python -m registry <命令>` |

### 工作流

- `submit.yml`：issue 带 `submission` 标签时检查并回复报告，通过则开合并请求。检查在只读权限的 job
  里运行（会安装并导入第三方代码，且子进程拿不到令牌），写权限的 job 只复制数据文件并重新校验。
- `update.yml`：每天发现新版本、重测每个插件最新的 3 个未撤回版本，校验后直接提交到 `main`。
- `pages.yml`：`main` 有推送或 `update` 完成时执行 `build`，把 `dist/` 强制发布到 `gh-pages`。
- `ci.yml`：非 `main` 分支和 PR 上跑测试，并校验全部数据。

首次启用需要：仓库设置里允许 GitHub Actions 创建合并请求；Pages 的来源选 `gh-pages` 分支。
用 `GITHUB_TOKEN` 创建的合并请求不会自动触发 `ci.yml`，合并前请留意报告。

### 常见操作

直接编辑数据文件，然后运行 `uv run python -m registry build` 校验。

- **调整分类**：修改 `plugins/<id>.json` 的 `category`（取 `categories.txt` 里的 ID）。
- **调整 tier**：修改 `plugins/<id>.json` 的 `tier`（`official` 或 `listed`）。
- **撤回某个版本**（yank）：给该版本的 `yanked` 写 `{"reason": "...", "since": "<UTC 时间>"}`。
  PyPI 侧的撤回会被自动同步，但 CI 永远不会清除撤回标记。
- **屏蔽**：在 `blocked.json` 添加条目，并删除 `plugins/` 下对应的文件（build 不允许两者同时存在）。
- **下架**：删除 `plugins/<id>.json` 和 `icons/<id>-*.png`，在 `removed.json` 追加一条记录。

### 本地命令

```text
uv sync
uv run pytest -q
uv run python -m registry build [--out dist]
uv run python -m registry icon <id> <文件或 https 地址>
uv run python -m registry discover [--id <id>]
uv run python -m registry test <id> [--version V] [--tenko-ref 标签 | --tenko-path 本地仓库]
uv run python -m registry retest
uv run python -m registry check-submission --source <包名|仓库@标签> --submitter <用户名> --category <ID> [--tags a,b] [--icon URL]
```

`test` 需要 `uv` 和网络；`check-submission` 会访问 GitHub API，设置环境变量 `GITHUB_TOKEN` 后才能查询协作者权限。
`test`、`retest` 和 `check-submission` 会直接安装并导入第三方代码，请在一次性环境里运行。
