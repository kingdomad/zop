# zop

一个面向批量操作和自动化场景的高吞吐 Zotero 命令行工具。

## 安装

从 PyPI 安装(推荐):

```bash
uv tool install zop-cli
```

也可用 pipx:`pipx install zop-cli`,或 pip:`pip install zop-cli`。安装后命令名为 `zop`。

开发安装(可编辑):

```bash
uv pip install -e .
```

## 配置

新建 `~/.config/zop/config.toml`:

```toml
[zotero]
data_dir = "D:\\Program Data\\zotero"
library_id = "12345"
api_key = "your-api-key"
```

读取操作走本地 SQLite(`data_dir/zotero.sqlite`),写入操作走 Zotero Web API。
读取无需联网,也不需要 API key。

## 用法

```bash
zop collection list                    # 列出所有集合
zop collection list --tree              # 以父子树形展示
zop collection items ABC12345           # 列出某集合下的条目
zop collection create "新主题"          # 创建集合
zop collection create "子主题" --parent "新主题"
zop collection delete ABC12345          # 删除集合(级联)
zop collection reparent ABC12345 --parent "新父级"
zop collection move KEY1 KEY2 --to TARGET_KEY   # 移动条目
zop collection plan plan.json --dry-run        # 校验批量计划
zop collection plan plan.json --execute       # 执行批量计划
```

## Agent skill

为 AI 编程助手(Claude Code、Codex、Cursor 等)配套了一个 [agent skill](https://skills.sh),教 agent 如何调用 `zop`、解析 JSON 信封输出、以及批量 plan 的 dry-run → execute 流程:

```bash
npx skills add kingdomad/zop --skill zop -a claude-code -y
```

详见 [`skills/zop/SKILL.md`](skills/zop/SKILL.md)。

## 与 `zot` 的差异

- **真正的批量**:创建集合使用 Zotero 的批量 POST(每请求 50 条)
- **有界并发 PATCH**:移动条目使用并行 PATCH(默认 8 路并发),而非逐条顺序调用
- **真正的 dry-run**:`zop collection plan --dry-run` 会实际检查名称冲突、父级解析与条目存在性
- **reparent 支持**:`zop collection reparent` 可用(`zot` 未暴露此能力)
- **单条失败隔离**:批量移动中某一条失败不会中断整批任务
