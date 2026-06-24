# zop — 架构与路线图

> **当前状态**:v0.1.0-alpha · 21 个测试通过 · ruff 无告警 · 测试覆盖率 34% · mypy 错误 23 个

`zop` 是一个从零打造的 Zotero CLI,专为**批量操作与自动化**场景而优化。
它使用自研的 httpx 客户端取代 `pyzotero`,引入了真正的 plan 校验机制,并提供了
`zot` 没有暴露的 reparent 支持。

## 项目概述

### 目标
- 高吞吐批量操作(并发地把 N 个条目移动到 M 个集合)
- 真正检查状态的 dry-run(而非字面意义的"预览")
- 通过 PATCH 实现集合 reparent(`pyzotero` 不支持)
- 为 Agent 消费设计的干净 JSON 信封
- 失败条目隔离的可预测错误处理

### 非目标(明确不在范围内)
- **MCP server** — 纯 CLI 工具即可
- **Bridge 插件**(Zotero 桌面端的 find-pdf/rename 集成)— `zot` 已具备
- **Workspace RAG**(embedding + 向量搜索)— `zot` 已具备,CRUD 不需要
- **GUI / TUI** — 只做 CLI
- **无本地 SQLite 时读取远端 Zotero 库** — 假定本地数据库存在

## 架构

### 分层模型

```
┌─────────────────────────────────────────────────────────────┐
│  CLI (click)                                                │
│  - Argument parsing                                         │
│  - Output formatting (JSON envelope / --human)              │
│  - Top-level error handling                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Service (business orchestration)                           │
│  - Input validation                                         │
│  - Name ↔ key resolution                                    │
│  - Multi-step operations (plan + topological sort)          │
│  - Bounded-concurrency batching                             │
│  - Per-item error aggregation                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Adapter (data source isolation)                            │
│  - SqliteReader: read-only local DB (with snapshot copy)    │
│  - ZoteroApi: async httpx Web API client (batch-capable)    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Models (pydantic v2)                                       │
│  - Collection / CollectionTree / Item / ItemSummary          │
│  - Envelope / Meta / ErrorBlock                             │
│  - Validation + serialization                              │
└─────────────────────────────────────────────────────────────┘
```

**为什么是四层**(而非 `zot` 的两层):
- Service 层从不直接 import `httpx` 或 `sqlite3` → 测试时可轻松 mock
- Adapter 层可替换(例如从 `httpx` 换成 `aiohttp`,无需改动 service)
- Models 在边界处强制类型校验;CLI 输出天然具备结构合法性
- 每一层职责单一,可以一次性装进脑子里

### 模块结构

```
src/zop/
├── cli.py                    # click entry: --json / --human / --quiet
├── __main__.py               # python -m zop
├── _version.py               # single source of truth (hatch reads it)
│
├── core/                     # cross-cutting infrastructure
│   ├── config.py             # TOML loader, auto-fallback to zot config
│   ├── errors.py             # ZopError tree + BatchResult generic
│   ├── envelope.py           # emit() / emit_batch() helpers
│   └── concurrency.py        # chunked() + (unused) bounded_gather
│
├── models/                   # pydantic v2
│   ├── common.py             # ItemType enum, ID_PATTERN
│   ├── collection.py         # Collection, CollectionTree
│   ├── item.py               # Item, ItemSummary
│   └── envelope.py           # Envelope, Meta, ErrorBlock
│
├── adapters/                 # I/O boundary
│   ├── sqlite_reader.py      # local Zotero DB (snapshot copy)
│   └── zotero_api.py         # async httpx Web API
│
├── services/                 # business logic
│   ├── collections.py        # CRUD + plan validate + topological create
│   ├── items.py              # search/read/update/delete/add
│   ├── tags.py               # batch add/remove
│   ├── notes.py              # list/add
│   ├── export.py             # BibTeX / CSL-JSON / RIS
│   ├── pdf.py                # text + outline via pypdf
│   └── library.py            # stats / recent / duplicates
│
└── commands/                 # thin click wrappers (no logic)
    ├── collection.py         # 7 subcommands
    ├── item.py               # 5 subcommands
    ├── tag.py                # 3 subcommands
    ├── note.py               # 2 subcommands
    ├── pdf.py                # 3 subcommands
    ├── export.py             # 1 subcommand
    └── library.py            # 3 top-level: stats, recent, duplicates
```

### 关键设计决策

| 决策 | 原因 | 备选方案 |
|------|------|----------|
| 使用 httpx async 而非 pyzotero | pyzotero 的 `addto_collection` 每次只能单条调用,我们需要批量 | pyzotero + 线程池(已否决:仍为每条一次调用) |
| SqliteReader 快照(拷贝到临时文件) | Zotero 持有 DB 锁,直接读取会超时 | `?mode=ro&immutable=1`(已否决:仍被锁);重试循环(已否决:不稳定) |
| 全部使用 Pydantic v2 | 一处声明即可同时获得自动校验和 JSON 序列化能力 | dataclasses + 手写 to_dict(已否决:样板代码过多) |
| Service 层将 `Collection.name` 解析为 `.key` | CLI 用 name 更友好,API 用 key 更友好 | 始终使用 key(已否决:对用户过于繁琐) |
| Plan:将 `create_many`(拓扑排序)与条目分配分离 | API 不接受指向尚未创建的集合的 parentCollection | 单次 bulk POST(已否决:父级引用会失败) |
| 所有输出统一采用 JSON 信封 `{ok, data, error, meta}` | Agent 可依赖单一结构,无需解析字符串 | 成功用 JSON,错误写到 stderr(已否决:对 Agent 不友好) |
| Service 层从不 import httpx/sqlite | 测试时可 mock,I/O 可替换 | service 直连 httpx(已否决:难以测试) |
| 采用 4 层而非 2 层 | 关注点分离;单文件更小 | 平铺结构(已否决:单文件 2000 行) |
| 使用 LIKE 搜索而非 FTS5 | 可移植,<100k 条目下足够快,无需额外配置 | FTS5 虚表(已否决:增加配置,收益有限) |
| 使用 pypdf 解析 PDF | 纯 Python,无原生依赖 | pdfplumber(已否决:更重);pdftotext 子进程(已否决:外部依赖) |

### 数据流示例

**读取(列出集合)**:
```
User → zop collection list
  → click parses args
  → commands/collection.py:list_cmd()
  → service.CollectionsService.list_all()
  → adapter.SqliteReader.list_collections()  [snapshot copy + SQL]
  → models.Collection (pydantic validates)
  → core.envelope.emit([...])                [JSON envelope]
  → stdout
```

**写入(批量移动条目,差异化亮点)**:
```
User → zop collection move K1 K2 K3 --to TARGET_KEY
  → commands/collection.py:move_cmd()
  → service.CollectionsService.move_items([K1,K2,K3], TARGET_KEY)
  → for each key: adapter.ZoteroApi.get_item(k)  [fetch current state + version]
  → adapter.ZoteroApi.batch_update_item_collections(updates)
       └─ asyncio.gather with Semaphore(8) + return_exceptions=True
       └─ per-item PATCH /items/{key}  (concurrent)
  → service aggregates (ok, fail)
  → core.envelope.emit_batch(succeeded, failed)
  → exit code 0/2
```

**Plan(重组)**:
```
User → zop collection plan plan.json --execute
  → load + parse plan JSON
  → service.CollectionsService.validate_plan(plan)
       ├─ check name conflicts vs current library
       ├─ resolve parent names (existing collections + intra-plan references)
       └─ check item existence
  → if not ok: emit report + exit 2
  → if ok: service.CollectionsService.create_many(plan)
       └─ topological waves (Kahn's algorithm)
       └─ each wave: ZoteroApi.create_collections(batch)
  → emit created collections + pending item assignments
```

## 当前状态

### 已完成(v0.1.0-alpha)
- ✅ 集合 CRUD(list / items / create / delete / reparent / move / plan)
- ✅ 条目 CRUD(search / read / update / delete / 通过 DOI 新增)
- ✅ 标签批量 add/remove
- ✅ Note list/add
- ✅ PDF read / outline / section(基于 pypdf)
- ✅ 导出:BibTeX、CSL-JSON、RIS
- ✅ 库级:stats / recent / duplicates
- ✅ JSON 信封输出,可通过 `--human` 切换
- ✅ 真正的 plan 校验(名称冲突、父级解析、条目存在性、plan 内拓扑序)
- ✅ 有界并发的批量 PATCH(默认 8 路)
- ✅ 基于快照的 SQLite reader(规避 Zotero 文件锁)
- ✅ 21 个单元测试通过
- ✅ Ruff 无告警

### 已知局限 / 待办

| 领域 | 状态 | 优先级 |
|------|------|--------|
| **Service 层写入测试** | `items.py` 0/92 行,`notes.py` 0/31 行,`tags.py` 0/65 行 | 高 |
| **Mypy strict** | 23 个错误(主要为 `no-any-return`、`unused-ignore`) | 中 |
| **CLI 命令测试** | 所有 command 文件覆盖率为 0% | 中 |
| **API mock 测试** | 未使用 `pytest-httpx` / respx,所有写路径未测试 | 高 |
| **真实 API 集成测试** | 未对接用户库做端到端验证(仅有 dry-run) | 低 |
| **CI** | 缺少 `.github/workflows/ci.yml` | 高 |
| **性能基准** | "高吞吐"声明缺少实测数据 | 低 |
| **LICENSE 文件** | pyproject 中只有 SPDX 表达式,缺少独立文件 | 低 |
| **CHANGELOG** | 尚未编写 | 低 |
| **Mypy 接入 CI** | 未自动运行 | 中 |
| **Pre-commit 钩子** | 尚未配置 | 低 |
| **群组库支持** | `--library group:ID` 标志未暴露 | 中 |
| **`zop config init`** | 交互式配置初始化 | 低 |
| **Pyzotero 替代范围** | Items service 直接使用了 `api._client`(私有属性) | 中(重构) |
| **`item move` 命令** | 目前仅有 `collection move`,缺少按 NAME 移动条目的命令 | 低 |
| **`item list`(分页)** | 目前仅有 `search` | 低 |
| **通过 Zotero `/items/new` 做 DOI 转写** | 当前 `--doi` 流程走 POST /items,较为脆弱 | 低 |

### 各模块测试覆盖率

```
Module                              Stmts   Miss   Cover
─────────────────────────────────────────────────────────
src/zop/adapters/sqlite_reader.py     122     42    66%   ← snapshot path untested
src/zop/adapters/zotero_api.py        122     85    30%   ← entire API surface
src/zop/core/concurrency.py            14      7    50%
src/zop/core/config.py                 35     15    57%
src/zop/core/errors.py                 52     10    81%
src/zop/core/envelope.py               29     29     0%   ← emit() untested
src/zop/models/collection.py           23      3    87%
src/zop/models/common.py               20      1    95%
src/zop/models/envelope.py             30      4    87%
src/zop/models/item.py                 21      0   100%
src/zop/services/collections.py       170     87    49%   ← create/move/reparent untested
src/zop/services/export.py              99      3    97%
src/zop/services/items.py              92     75    19%
src/zop/services/library.py            17      1    94%
src/zop/services/notes.py              31     20    35%
src/zop/services/pdf.py                89     77    13%
src/zop/services/tags.py               65     51    22%
src/zop/commands/*.py                 494    494     0%   ← all CLI
─────────────────────────────────────────────────────────
TOTAL                               1598   1056    34%
```

## 路线图

### v0.2.0 — API 正确性与覆盖率(下一阶段)
- [ ] 为所有写入路径(items/tags/notes)添加 `pytest-httpx` mock 测试
- [ ] 重构 services,只使用 adapter 公开方法(禁止访问 `api._client`)
- [ ] 修复全部 23 个 mypy 错误
- [ ] 为 `core/envelope.py` 的 `emit/emit_batch` 添加测试
- [ ] 通过 `click.testing.CliRunner` 增加 CLI smoke 测试
- **目标**:80% 覆盖率,mypy 零错误,所有批量操作通过校验

### v0.3.0 — CI 与打包
- [ ] GitHub Actions:push/PR 时运行 ruff + mypy + pytest
- [ ] 验证 `uv build`(sdist + wheel)
- [ ] 添加 `LICENSE` 文件(MIT)
- [ ] 添加 `CHANGELOG.md`(遵循 Keep a Changelog 格式)
- [ ] 配置 pre-commit 钩子
- [ ] 发布首个 GitHub Release(v0.3.0 tag)
- **目标**:可通过 GitHub Releases 直接 pip 安装

### v0.4.0 — 打磨与扩展
- [ ] 群组库支持(`--library group:ID`)
- [ ] `zop config init` 交互式配置
- [ ] `item move`(按 NAME 移动条目到集合)
- [ ] `item list` 分页(`--limit`、`--offset`、`--sort`)
- [ ] 大结果集 NDJSON 流式输出(`--stream` 标志)
- [ ] 性能基准脚本(`bench/`):N 个条目移动到 M 个集合
- [ ] 通过 Zotero 官方的 `/items/new` 端点实现 DOI 转写
- **目标**:可处理 10k 条目的库而不阻塞

### v0.5.0 — 可选特性(取决于用户需求)
- [ ] `zop workspace new/query`(替代 `zot` 的 workspace RAG)
- [ ] `zop find-pdf`(不依赖 bridge 插件,改用 Zotero Web 搜索)
- [ ] Webhook / 守护进程模式,监听库变更通知
- [ ] 自定义条目类型导出器的插件系统(BibLaTeX 等)

### v1.0.0 — 稳定版
- [ ] 公开 API 冻结
- [ ] 95% 测试覆盖率
- [ ] 全量类型覆盖(mypy --strict)
- [ ] 性能预算达成:50 条目的批量移动 < 5 秒
- [ ] 提供从 `zot` 到 `zop` 的升级路径(配置迁移脚本)
- [ ] 发布到 PyPI

## 设计决策日志

### 为什么不做 MCP server
- 用户明确要求"仅 CLI 工具"
- MCP 会让对外接口面积翻倍,并引入 ASGI 服务器依赖
- 后续可作为薄包装单独提供:`zop-mcp` 包以子进程方式调用 `zop`

### 为什么不使用 FTS5
- 在当前规模下,基于 title/abstract/creators 的 LIKE 搜索已经够快(在 76 条目的库上测试,<50ms 返回)
- FTS5 要么在启动时构建索引,要么在写入时维护索引 — 两者都增加复杂度
- 后续可通过 `SearchBackend` 接口无侵入地替换为 FTS5

### 为什么是 4 层而非 2 层
- `zot` 的两层设计(commands → core)导致 command 文件臃肿,I/O 与业务混杂
- 4 层:每个文件 <250 行,每层可独立测试
- 代价是间接性,但对于 >1k LOC 的项目是值得的

### 为什么用 pydantic v2 而非 dataclasses
- 一处声明即可同时获得校验与序列化能力
- 自动生成 JSON Schema(未来:可作为 MCP 的 OpenAPI 来源)
- 在我们的规模下性能足够(Rust 内核)

### 为什么不使用 SQLite FTS5
- 增加配置步骤,当前 LIKE 足够快
- 从我们视角看 Zotero 的 DB 是只读的,FTS 索引只能是一份拷贝

### 为什么用 JSON 信封(而非"成功用 JSON,错误写 stderr")
- Agent 希望解析单一结构;stdout 数据 + stderr 错误的组合很脆弱
- `--human` 标志可切换为美观的表格输出
- `meta` 块携带调试信息(request_id、latency_ms、count)

## 参考资料

- Zotero Web API 文档:https://www.zotero.org/support/dev/web_api/v3/start
- Zotero SQLite schema:本仓库中的 `tools/inspect_sqlite.py`(运行它进行验证)
- pyzotero(已规避但作为参考):https://github.com/urschrei/pyzotero
- Skill(zot 上下文):`.agents/skills/zotero-cli-cc/SKILL.md`
