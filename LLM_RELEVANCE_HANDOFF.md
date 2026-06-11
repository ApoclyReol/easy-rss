# LLM 相关性判定输出简化交接

## 背景

本次任务目标是：LLM 判断 RSS 条目是否相关时，只返回“是否相关”，不返回理由、解释、分析过程或 JSON 中的 `reason` 字段。

重要路径纠正：

- 真实代码目录是 `/Users/apocly/code/rss_reader`
- `/Users/apocly/Documents/rss_reader` 是一个空 Git 仓库，本次误入后已清理，当前无残留改动

## 已完成改动

新增 `app/relevance.py`：

- 定义 `RelevanceItem`
- 定义 `build_relevance_prompt(item, user_interest)`
- 定义 `item_from_record(record)`
- 定义 `parse_relevance_response(response_text)`
- 输出契约固定为：
  - `true`：相关
  - `false`：不相关
- 解析逻辑只接受严格的 `true` / `false`
- 以下输出会被拒绝：
  - `true because ...`
  - `{"relevant": true, "reason": "..."}`
  - `相关`
  - `不相关`
  - 空字符串

新增 `tests/test_relevance.py`：

- 验证 prompt 明确要求只返回 `true` / `false`
- 验证解析函数接受大小写和前后空白归一后的 `true` / `false`
- 验证带理由、JSON、中文枚举、空输出都会抛出 `ValueError`
- 验证 `item_from_record()` 能从现有 reader item 字段生成 `RelevanceItem`

更新 `README.md`：

- 新增 “LLM 相关性判定输出契约” 小节
- 明确不要返回 JSON、`reason` / `理由` / `explanation` 字段或分析过程

## 验证结果

已在 `/Users/apocly/code/rss_reader` 下通过：

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/rss_reader_pycache python3 -m py_compile app/relevance.py tests/test_relevance.py
```

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/rss_reader_pycache python3 -m unittest tests.test_relevance
```

测试结果：

```text
Ran 4 tests in 0.000s
OK
```

说明：需要设置 `PYTHONPYCACHEPREFIX=/private/tmp/rss_reader_pycache`，否则系统 Python 可能尝试写入 macOS 默认 cache 目录并触发权限问题。

## 当前 Git 状态

真实项目 `/Users/apocly/code/rss_reader` 当前有这些改动：

```text
 M README.md
?? app/relevance.py
?? tests/
?? LLM_RELEVANCE_HANDOFF.md
```

## 后续继续任务建议

下一步如果要真正接入 LLM 自动筛选，可以从 `app/relevance.py` 复用：

- 用 `item_from_record(item)` 把数据库条目转为 LLM 输入
- 用 `build_relevance_prompt(...)` 生成 prompt
- 调用 LLM 后用 `parse_relevance_response(...)` 得到布尔值
- 不要在数据库、UI、日志中新增或依赖 `reason` 字段

如果接入到 Streamlit UI，建议保持用户可见结果简单：

- 只展示是否相关或直接更新 `is_interested`
- 不展示 LLM 理由
- 遇到非 `true` / `false` 输出时显示简短错误，例如 “LLM 返回格式不符合要求”

