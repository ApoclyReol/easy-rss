# 提交规范

本项目的提交信息同时承担版本记录和变更摘要职责。每个可发布的提交都必须让维护者仅通过 `git log` 看出版本、变更类型和主要内容。

## 1. 标题格式

```text
vMAJOR.MINOR.PATCH <type>: <简短变更内容>
```

示例：

```text
v1.1.0 feat: 增加未读篮子个性化推荐
v1.1.1 bug: 修复空推荐结果导致页面报错
v1.1.2 docs: 补充本地数据隔离与故障排查说明
v1.2.0 feat: 增加关键词词表人工修正
```

版本号和类型都不能省略。标题保持一行、简洁、使用中文描述具体结果。

## 2. 变更类型

| 类型 | 使用场景 |
| --- | --- |
| `feat` | 新增用户可见功能或能力 |
| `bug` | 修复用户可见错误、数据错误或兼容性问题 |
| `docs` | 只修改 README、维护文档或产品文档 |
| `refactor` | 不改变用户行为的代码重构 |
| `test` | 只增加或调整测试 |
| `chore` | 依赖、脚本、构建或仓库维护 |
| `security` | 凭据、数据边界或安全策略变更 |
| `perf` | 不改变功能语义的性能优化 |

不要使用含糊的 `update`、`修改`、`misc` 作为类型。

## 3. 版本递增规则

- `MAJOR`：不兼容的使用方式、数据结构或公开接口变化。
- `MINOR`：向后兼容的新功能，通常对应 `feat`。
- `PATCH`：向后兼容的 bug 修复、文档修正或小型维护变更。
- 只改文档时可以使用 `vX.Y.Z docs`，但仍需按实际变更决定是否递增 patch。
- 版本号必须与 `app/config.py` 中的 `APP_VERSION` 一致。
- 同一批紧密耦合的代码、测试和文档应放在同一个提交，不要拆成无法独立验证的半成品提交。

## 4. 提交正文

当变更超过一个独立动作时，在标题后增加编号列表：

```text
v1.1.0 feat: 增加未读篮子个性化推荐

1. 新增关键词模型和推荐数据表
2. 将高相关、待判断和低相关论文整合到未读篮子
3. 增加待判断论文的主动 LLM 复核
4. 补充测试、PRD 和故障排查文档
```

正文应描述结果，不要粘贴完整日志、凭据、临时路径或无关的试错命令。

## 5. CHANGELOG 要求

- `feat`、`bug`、`security` 和影响用户行为的 `refactor` 必须同步 [CHANGELOG.md](../CHANGELOG.md)。
- CHANGELOG 的版本标题、日期和提交版本号保持一致。
- bug 修复应简要写清问题和结果；安全变更不要暴露秘密细节。
- 未发布变更可以先记录在 `Unreleased`，正式提交时再归入对应版本。

## 6. 提交前检查

```bash
git status --short
git diff --check
git add -A
git diff --cached --stat
git diff --cached -- data/ .env .venv
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m unittest discover -s tests -v
```

暂存区不得包含：

- `data/rss_reader.sqlite3` 及其 SQLite sidecar
- `data/settings.json`
- `.env`、API Key、token、密码或真实导出数据
- `.venv/`、`__pycache__/`、临时日志和本机绝对路径

## 7. 发布与推送

推送前确认：

1. `APP_VERSION`、CHANGELOG 和提交标题使用同一个版本号。
2. 完整测试和启动健康检查通过。
3. 暂存区只包含预期源代码、测试和文档。
4. 远程分支和本地分支关系明确，避免直接覆盖他人提交。

默认推送当前分支；如果需要 Pull Request，标题沿用提交标题，正文使用编号列表说明行为变化、测试结果和数据/LLM 影响。
