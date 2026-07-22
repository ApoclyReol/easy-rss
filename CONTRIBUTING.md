# 贡献指南

## 开始之前

1. 阅读 [README.md](README.md) 了解用户流程。
2. 阅读 [维护者快速入门](docs/AGENT_QUICKSTART.md) 了解模块边界和数据状态。
3. 阅读 [PRD](docs/PRD.md) 与 [设计系统](docs/DESIGN_SYSTEM.md) 确认推荐行为和 UI 约束。
4. 阅读 [提交规范](docs/COMMIT_CONVENTION.md) 了解版本号、变更类型和发布检查。
5. 确认 `data/`、`.venv/` 和 `.streamlit/` 没有被加入暂存区。

## 模块边界

- `app/streamlit_app.py`：初始化和页面路由。
- `app/views/`：Streamlit 展示和交互。
- `app/services/`：RSS、推荐、LLM、维护和统计业务逻辑。
- `app/repositories/`：SQLite 查询、写入和聚合。
- `app/ui/`：通用通知和 UI 辅助。

SQL 不放在 view 中，模型训练不放在 Streamlit 回调中，论文状态只通过 repository 层修改。

## 本地开发

```bash
./run.sh
```

运行测试和静态检查：

```bash
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

不需要提交本地数据库或配置。新建测试时优先使用临时 SQLite，并通过 patch 指向临时 `DB_PATH`，不要让测试修改真实 `data/rss_reader.sqlite3`。

## 变更规则

- 用户可见行为必须同步 README、PRD 或设计系统。
- 数据库新增表或字段必须在 `app/db.py` 中使用幂等初始化，并补测试。
- 推荐排序、阈值和状态流转变化必须补充正向、边界和失败场景测试。
- 任何批量状态修改都必须有明确范围、确认和恢复路径。
- 不要恢复已移除的独立布尔筛选页；推荐入口统一位于未读篮子。

## 提交与 Pull Request

完整规则见 [提交规范](docs/COMMIT_CONVENTION.md)。提交标题必须使用“版本号 + 类型 + 变更内容”格式，例如：

```text
v1.1.0 feat: 整合未读篮子个性化推荐
v1.1.1 bug: 修复空推荐结果导致页面报错
v1.1.2 docs: 补充安全和故障排查文档
```

类型至少区分 `feat`、`bug`、`docs`、`refactor`、`test`、`chore`、`security` 和 `perf`；版本号必须与 `app/config.py` 的 `APP_VERSION` 和 `CHANGELOG.md` 一致。多个独立变更在正文中使用编号列表。

提交前执行：

```bash
git status --short
git diff --check
git add -A
git diff --cached --stat
git diff --cached -- data/settings.json data/rss_reader.sqlite3
.venv/bin/python -m unittest discover -s tests -v
```

最后一条 diff 检查不应显示任何本地数据文件。PR 描述应说明行为变化、迁移影响、测试结果和是否涉及 LLM 外发数据。
