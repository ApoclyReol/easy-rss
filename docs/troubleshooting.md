# RSS Reader 故障排查

## 1. 启动失败

### 找不到 Python

确认系统有 Python 3，并从项目根目录运行：

```bash
./run.sh
```

脚本会优先使用 `uv` 创建 `.venv`；没有 `uv` 时使用 Python 自带的虚拟环境和 pip。

### 依赖安装失败

检查网络和 Python 版本，然后手动执行：

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

如果没有 `uv`：

```bash
.venv/bin/python -m pip install -r requirements.txt
```

项目代码和依赖必须使用同一个 `.venv/bin/python`。

## 2. 端口被占用

Streamlit 默认使用 8501。如果看到端口占用：

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
```

确认旧的 Streamlit 进程后再停止它，或临时使用其他端口：

```bash
.venv/bin/python -m streamlit run app/streamlit_app.py --server.port 8502
```

## 3. 数据库问题

数据库位置是 `data/rss_reader.sqlite3`，配置位置是 `data/settings.json`。两者都属于本地数据，不应上传。

只读检查数据库完整性：

```bash
sqlite3 -readonly data/rss_reader.sqlite3 "PRAGMA integrity_check;"
```

正常结果应为 `ok`。如果出现 `-wal`、`-shm` 或 `-journal` 文件，不要单独删除；先停止应用，再备份整个 `data/` 目录。

应用启动时会执行幂等的 `CREATE TABLE IF NOT EXISTS`，推荐表缺失时会自动创建，不会删除已有论文状态。

## 4. RSS 没有新论文

在“订阅管理”检查：

- 订阅源是否启用。
- RSS URL 是否仍可访问。
- 订阅源最近一次错误信息。
- 手动更新是否成功。

对单个订阅源先手动更新，确认错误信息后再批量操作。不要因为一次网络失败删除订阅源。

## 5. 推荐没有结果

推荐不会在启动或 RSS 更新后自动执行。在“文献阅读 → 未读”点击“更新关键词推荐”。

以下情况会保持“未评分”：

- 正样本或负样本不足。
- 论文标题和摘要都为空。
- TF-IDF 词表无法构建。

正样本来自 `interested / archived`，负样本来自 `hidden / expired`。这些状态的数量可以在“兴趣分析”或数据库只读查询中确认。

## 6. LLM 复核失败

检查“推荐设置 → LLM 配置”：

- `base_url` 是否为 OpenAI 兼容接口地址。
- API Key 是否仍有效。
- `model` 是否是服务商支持的模型名。
- 是否先运行了关键词推荐并产生待判断论文。

使用“测试 API 连接”确认连接、认证和模型状态。单篇复核失败会留在待判断层，再次点击只重试失败项。

不要在日志、截图或 issue 中粘贴 API Key。

## 7. 推荐排序看起来不合理

先打开推荐设置检查关键词：

- 错误关键词可以禁用。
- 稳定偏好可以设置人工正向或负向权重。
- 修改后必须再次点击“更新关键词推荐”。

推荐层级不改变论文状态。若误隐藏论文，使用“撤回”或到“已隐藏”篮子恢复到未读。

## 8. 测试与启动烟雾检查

```bash
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m streamlit run app/streamlit_app.py --server.headless true --server.port 8765
curl http://127.0.0.1:8765/_stcore/health
```

健康检查应返回 `ok`。检查完成后停止临时 Streamlit 进程。
