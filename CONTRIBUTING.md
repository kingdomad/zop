# 贡献与维护指南

面向 zop 的贡献者与维护者。终端用户的安装/使用请看 [README](README.md);架构设计请看 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 开发环境

前置:**Python ≥ 3.12** 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/kingdomad/zop.git
cd zop
uv sync                # 创建 .venv 并安装主依赖 + dev 依赖(ruff/mypy/pytest 等)
uv run zop --version   # 验证可运行
```

## 项目结构

四层(端口/适配器)架构,详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md):

```
src/zop/
├── core/        # 横切:config / errors / envelope / concurrency
├── models/      # pydantic v2 数据模型 + 信封
├── adapters/    # I/O 边界:sqlite_reader(读)/ zotero_api(写,async httpx)
├── services/    # 业务编排(只调 adapter 公共方法)
└── commands/    # 薄 click 包装(无业务逻辑)
```

**核心约束:service 层不得直接 import `httpx` / `sqlite3`** —— 只通过 adapter 的公共方法访问 I/O。这是可测试性和可替换性的基础。

## 日常开发命令

```bash
uv run ruff check .        # lint(含 tools/、tests/)
uv run ruff format         # 格式化
uv run mypy src            # 严格类型检查(必须 0 错误)
uv run pytest              # 全量测试 + 覆盖率报告
uv run pytest tests/test_collections.py -v   # 单个文件
uv run pytest -k plan      # 按名筛选
```

四者全绿才能提交。CI 跑的是同样的检查,本地绿 ≈ CI 绿(但 CI 在 Linux,注意跨平台)。

## 测试约定

- **栈**:pytest + pytest-asyncio(`asyncio_mode = "auto"`,async 测试无需逐个 mark)+ pytest-cov。
- **fake_db**:`tests/conftest.py` 提供一个**空** sqlite 文件(SqliteReader 只检查路径存在);需要真实 schema 的测试在本地自建 —— 见 `tests/test_collections.py`(完整 10 表)和 `tests/test_cli_plan.py`(按需建表)。
- **写入路径**:adapter 测试用 `httpx.MockTransport`(零依赖,不引 pytest-httpx);service 测试用 `AsyncMock(spec=ZoteroApi)` 注入。
- **夹具**:自动化夹具放 `tests/fixtures/`(如 `test_plan.json`);一次性手工夹具别入库。
- **覆盖率**:当前 ~64%,无 `--cov-fail-under` gate。优先覆盖关键写入路径和 CLI 命令,不为数字硬凑。

## 代码风格

- ruff:line-length 100,启用 E/W/F/I/B/UP/N/S/C4/RET/SIM/TID/PT/RUF;`tests/` 放宽 S101(assert)。
- mypy:`strict = true`,对外部 `pypdf.*` 用 `ignore_missing_imports`。
- 导入:禁止相对导入(`flake8-tidy-imports: ban-relative-imports = "all"`)。

## 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/):`feat` / `fix` / `test` / `refactor` / `chore` / `build` / `ci` / `docs`。一个逻辑单元一个原子提交。

历史示例:`feat(skills): ...`、`test(plan): ...`、`build: rename distribution to zop-cli`。

## CI

`.github/workflows/ci.yml` 在 push/PR 到 `main` 时触发,三个并行作业:

| 作业 | 内容 |
|------|------|
| Ruff | `ruff check`(全仓库) |
| Mypy | `uv sync` + `mypy src`(strict) |
| pytest | 矩阵 Python 3.12 / 3.13,`uv sync` + `pytest --cov-report=xml` |

无覆盖率门槛 —— 测试全过即绿。

## 版本管理

单一来源:`src/zop/_version.py` 的 `__version__`(hatchling 读取,注入构建元数据)。发版流程:

1. 改 `__version__`(如 `"0.3.0"`);
2. 提交(`chore: bump version to 0.3.0`);
3. 打 tag:`git tag v0.3.0 && git push --tags`;
4. 按下一节发布到 PyPI。

## 发布到 PyPI

分发名是 **`zop-cli`**(命令仍是 `zop`,导入包仍是 `zop`)。

**1. 配置 token**(一次性):在 PyPI 为 `zop-cli` 项目建一个 scoped API token,设为环境变量。uv **不读** `~/.pypirc`,用环境变量:

```powershell
# Windows(用户级,持久)
[Environment]::SetEnvironmentVariable("UV_PUBLISH_TOKEN", "pypi-xxxxxxxx", "User")
```

```bash
# macOS / Linux
echo 'export UV_PUBLISH_TOKEN=pypi-xxxxxxxx' >> ~/.bashrc
```

**2. 构建 + 校验**:

```bash
uv build                       # 产出 dist/zop_cli-X.Y.Z-*.whl 和 .tar.gz
uvx twine check dist/*         # 校验元数据(License-Expression、entry point 等)
```

**3. 发布**:

```bash
uv publish                     # 自动读取 UV_PUBLISH_TOKEN
```

**4. 验证**:换一个干净环境 `uv tool install zop-cli` 从 PyPI 装回来,确认 `zop --version` 和命令正常。

**备选(自动化)**:在 GitHub Actions 用 [trusted publishing](https://docs.pypi.org/trusted-publishers/)(OIDC,免本地 token)—— 打 tag 触发 workflow 自动发布。适合稳定后接入。

## 维护 agent skill

仓库带一个面向 agent 的 skill(`skills/zop/`),用户通过 `npx skills add kingdomad/zop --skill zop` 安装。

- **改 CLI 命令后,同步更新 `skills/zop/SKILL.md` 的命令表** —— agent 会照表调用,表里写错命令会导致 agent 调用失败。
- skill 的 frontmatter `description` 只写"何时触发",不总结工作流(否则 agent 会只读 description 跳过正文)。
- `skills/` 入库发布;`.claude/skills/` 是本地实验性 skill,**已 gitignore**,不会随仓库发布。

## .gitignore 约定

以下不入库(已在 `.gitignore`):`.claude/`、`.serena/`、`.venv/`、`.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`、`.coverage`、`*.sqlite`。新增临时/本地文件时遵循同样原则。
