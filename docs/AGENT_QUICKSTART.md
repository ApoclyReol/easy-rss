# RSS Reader Agent Quickstart

这份文档用于帮助新的 agent 或维护者快速恢复项目上下文，理解当前架构、数据模型、关键流程和维护边界。

## 1. 项目定位

`rss_reader` 不是正式文献管理器，而是一个 **RSS 初筛分拣台**。

核心目标：

1. 抓取期刊 RSS
2. 去重并入库
3. 快速把文献分到不同状态篮子
4. 用统计结果反过来理解哪些期刊更值得持续关注

最终真正需要长期保存的文献，用户会手动下载到外部文件管理软件或文献管理软件中。

## 2. 当前架构

入口：

- `app/streamlit_app.py`

职责分层：

- `app/views/`：页面视图
- `app/services/`：业务逻辑、RSS 更新、个性化推荐、自动更新、统计辅助
- `app/repositories/`：SQLite 查询与聚合
- `app/ui/`：通知等界面辅助

提交和版本规则见：

- `docs/COMMIT_CONVENTION.md`
- 根目录 `CONTRIBUTING.md`

保持原则：

- `streamlit_app.py` 只做初始化和 tab 路由
- SQL 不要散落到视图层
- 新的状态、统计、排序规则优先落在 repository/service 层，再由 view 调用

## 3. 数据库形态

核心文献数据是三表结构，并增加三张推荐持久化表：

### `feeds`

订阅源表，字段包括：

- `id`
- `name`
- `url`
- `enabled`
- `created_at`
- `updated_at`
- `last_checked_at`
- `last_error`

### `items`

文献主表，字段包括：

- `id`
- `stable_guid`
- `title`
- `title_norm`
- `authors`
- `journal`
- `year`
- `doi`
- `link`
- `pub_date`
- `summary`
- `first_seen_at`
- `last_seen_at`
- `item_status`

### `item_feeds`

文献与订阅源关系表，字段包括：

- `item_id`
- `feed_id`
- `first_seen_at`
- `last_seen_at`

### 推荐表

- `recommendation_scores`：未读论文的关键词分、最终层级、LLM 复核和模型版本
- `recommendation_keywords`：自动词权重、样本频次及人工修正
- `recommendation_models`：每次主动重建的版本、样本数和错误信息

### 期刊名称统一口径

- 标准期刊名统一以 `feeds.name` 为准
- `items.journal` 保留这个标准期刊名，不再把 RSS 条目里的 `Source` 或卷期文本当成主口径
- 新抓取条目直接写入 `feeds.name`
- 维护任务会执行一次 journal 同步，把历史条目回填到对应的订阅名称
- 订阅名称被编辑后，关联条目的 `items.journal` 也会同步更新

### 文献 identity 规则

- `stable_guid` 优先使用 DOI
- 没有 DOI 时，正式文献优先使用 `title_norm + year + authors`
- 不要再把可编辑的订阅名称当作正式文献 identity 的核心组成部分
- 对没有作者、没有 DOI 的低信息条目，仍保留期刊名参与 identity，避免像 `Editorial Board` 这类通用题名跨期刊误并

## 4. 状态模型

当前只使用 **单字段状态模型**，唯一状态源为 `items.item_status`。

允许值：

- `unread`
- `interested`
- `archived`
- `hidden`
- `expired`

不要回退到多布尔字段。

### 状态语义

- `unread`：刚入库、未处理
- `interested`：准备进一步看
- `archived`：最终确认值得保留
- `hidden`：暂时或明确不想看
- `expired`：隐藏太久，由规则自动过期

### 典型流转

- `unread -> interested`
- `interested -> archived`
- `archived -> interested`
- `unread / interested / archived -> hidden`
- `hidden -> expired`
- `hidden / expired -> unread`

## 5. 阅读页当前心智

阅读页顶部篮子：

- 未读
- 感兴趣
- 已归档
- 已隐藏
- 已过期

列表默认排序：

- 未读篮子按 `高相关 -> 待判断 -> 未评分 -> 低相关`，同层按最新优先
- 其他篮子按 `last_seen_at DESC, id DESC`

阅读页同时承担单条分拣和未读推荐；批量操作仅限确认后隐藏当前筛选范围的低相关论文。

当前阅读页保留：

- 订阅源筛选
- 搜索
- 显示数量
- 列表浏览 / 快速处理
- 最近一步撤回
- 主动更新关键词推荐
- 主动 LLM 复核待判断论文
- 查看并修正关键词词表

不要增加无推荐依据的“当前筛选全部隐藏”。

## 6. 更新与自动整理

更新主链路在：

- `app/services/feed_service.py`
- `app/services/auto_update_service.py`

当前规则：

- 应用每次启动时，只自动更新一次
- 不做持续定时更新
- 手动“更新订阅”也走同一条数据刷新链路

数据刷新链路：

1. 更新 RSS 订阅
2. 记录本轮更新摘要
3. 自动检查隐藏文献是否应转为过期

### 过期规则

- 只处理当前 `hidden` 文献
- 根据 `last_seen_at` 判断
- 当前默认阈值：`30` 天
- 不要求用户手动点“执行过期”

这条规则应继续保持“数据驱动”，不要重新变回手动批量维护逻辑。

### 一次性维护任务

- 维护入口：`app/services/maintenance_service.py`
- 通过 `data/settings.json` 里的 `data_maintenance_version` 控制，只在版本升级时执行一次
- 当前维护任务会做：
  - 统一 `items.journal` 到 `feeds.name`
  - 合并历史重复文献，优先保留人工状态
  - 重建旧的 `stable_guid`
  - 拆分低信息多订阅误并条目

不要把这类修复逻辑重新塞回普通页面 rerun 热路径。

## 7. 个性化推荐

### 关键词推荐

- 训练标签：`interested / archived` 为正，`hidden / expired` 为负
- 未读不参与训练，只接受评分
- 标题重复输入以提高权重，摘要作为补充；不使用作者和期刊作为特征
- 英文和中文统一分词，TF-IDF 使用一元和二元词组
- 类别平衡逻辑回归输出 `0–100`，阈值为高相关 `>=70`、低相关 `<=30`
- 评分以无关键词证据时的 `50` 为中性点，只由实际命中的正负关键词向两端推动，避免负样本总量形成错误低分
- 每次点击“更新关键词推荐”完整重建，旧 LLM 结果随之失效
- 空文本或训练失败保持未评分，不得自动归为低相关

### LLM 复核

- 只处理关键词层级为 `pending` 且尚未成功复核的未读论文
- 输出契约严格为 `high / low`
- 单篇失败保留在待判断层，再次点击只重试失败项
- 推荐和 LLM 均不得由启动或 RSS 更新自动触发

## 8. 兴趣分析

页面：

- `app/views/analytics.py`

当前按期刊统计：

- 总条目
- 未读
- 隐藏
- 感兴趣
- 归档
- 过期
- 兴趣文献数
- 感兴趣率

定义：

- 兴趣文献 = `interested + archived`
- 感兴趣率 = `(interested + archived) / (hidden + interested + archived)`

注意：

- 表格默认按感兴趣率 **数值降序**
- 不要用百分号字符串直接参与排序

## 9. CNKI 特别规则

CNKI 链接不能像普通 RSS 链接那样直接去掉 query 参数。

原因：

- CNKI 文章详情定位依赖 query
- 如果清掉 query，会把不同文章都变成同一个失效链接：
  `https://kns.cnki.net/kcms2/article/abstract`

当前规则在：

- `app/rss_core.py -> canonicalize_link()`

要求：

- `cnki.net` 链接保留 query
- 其他站点仍可做 query 清理

这是一个高优先级兼容点，后续修改 RSS 链接规范化逻辑时不要破坏。

## 10. 本地配置与隐私

本地配置文件：

- `data/settings.json`

内容包括：

- LLM 配置
- 自动更新摘要
- 过期天数

要求：

- 只保存在本地
- 不应提交 API key
- `.gitignore` 已忽略该文件

推荐数据文件也全部位于 `data/`，包括 SQLite 主文件及 `-wal`、`-shm`、`-journal` sidecar；这些文件不应进入 Git。

## 11. 验证方式

常用检查：

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/rss_reader_pycache python3 -m py_compile app/*.py app/**/*.py
```

推荐测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

如果涉及依赖 `bs4`、`streamlit` 等项目环境，请优先使用 `.venv/bin/python`。

## 12. 维护注意事项

- 优先保持单字段状态模型，不要引入多状态布尔位
- 批量状态整理优先放到更新流水线或专门分析/管理页，不要堆到阅读页
- 新统计口径先写清“定义”，再进页面
- 排序逻辑要尽量全局一致，避免不同篮子各有一套心智
- 如果未来需要真正分析“感兴趣 -> 归档”的历史转化，再新增事件表，不要在当前表上硬拼
