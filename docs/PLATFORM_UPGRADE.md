# YuReader 个人学习平台升级 — 阶段一

更新日期：2026-08-29
基线：`a3c08fba54af40312e9b090034852735b56233f2`（`yureader-v0.9.0-platform-baseline`）
分支：`feature/personal-learning-platform`

本文记录真实体检结论、平台边界、信息架构、数据模型、兼容迁移策略、阅读与练习的关联契约、分阶段实施计划和风险回退方式。它不是一份愿景文档，而是基于当前代码与真实数据可回退的升级执行说明。

---

## 0. 体检方法

- 完整阅读 `AGENTS.md`、`README.md`、`docs/STATUS.md` 与 `app.py`、`static/index.html`、`static/app.js`、`static/reader.css`、`static/styles.css`。
- 读取正式书架中一本代表包的 `manifest.json`（schema_version 2），确认目录树、稳定小节 ID、来源映射与阅读/参考页的字段契约。
- 实时请求 `/api/bootstrap`、`/api/health`，并用真实浏览器核对当前首页、书架、阅读页、笔记、复习、日志、统计的实际行为。
- 参考 `C:\Users\Yu\Documents\YuQuiz\AGENTS.md` 与 `README.md` 后，只读抽出可复用的通用模式（分科待办、Obsidian 归档、克制视觉），不合并其题库业务。

体检结论：现有 11 本正式书籍全部是 schema_version 2 的合法包，共 863 个稳定小节、合计 164 个正式章节分组；服务运行正常，浏览器无控制台错误、无横向溢出。

## 1. 新产品边界

YuReader 是用户本人使用的本地个人学习平台。核心流程：

```text
阅读资料 → 侧边栏 AI 理解 → 章节笔记 → Obsidian 备份
        → 对应练习（独立模块）→ 昨日复习 → 学习日志
```

本阶段明确边界：

- **阅读是核心，不能被题库功能淹没。** 练习是引用知识位置的独立模块，不进入正文阅读流程，也不参与章节笔记与复习的现有机制。
- YuReader 只组织与保存上下文，不内置模型调用；侧边栏 AI 继续负责理解、复习与总结。
- 不建设模拟考试、复杂组卷、记忆曲线、打卡奖励或付费 API。没有真实题库样本验证前，不建任何练习界面。
- 不把 MinerU 粗产物、OCR 水印、未清洗的题目当正式资料发布。
- YuQuiz 保持只读参考；不修改、迁移或依赖其 `study.db`、用户数据与运行目录。
- 不得删除或重新生成用户现有数据；不修改 `C:\Users\Yu\Downloads` 原始 PDF、`C:\Users\Yu\Documents\YuBook-Staging\politics-2026` 的 MinerU 产物与 OneDrive 原始教材。
- 新增学习领域（政治/英语）本阶段只建立分类空壳与契约，不批量制作或导入对应资料。

## 2. 信息架构

顶层以学习领域划分书架：

```text
学习领域 domain
  └─ 学科 subject
       └─ 资料 resource（一本教材、一份讲义、一个题库或一份参考）
            ├─ 章节 chapter
            │    └─ 小节 section（现有稳定阅读页）
            └─ 对应习题 question（未来独立练习模块，依知识位置关联）
```

- domain：`medicine / politics / english`，对应 医学 / 政治 / 英语。
- subject：学科名，例如 口腔正畸学、马克思主义基本原理。
- resource：具体资料（正式书架的一本书或一份资料包）。
- resource_type：`book / lecture / question_bank / reference`。

现有书籍在运行时**没有新字段时安全回退**：

```text
domain        = medicine
resource_type = book
subject       = 书名（医学学科即资料名，不另造映射）
```

不批量改写当前正式书架包（`content/**/manifest.json`、正文、章节 ID、笔记路径、阅读进度与统计均不动）。领域字段作为可选的清单元数据写入 manifest 的 `book` 节点，缺失时按上述回退。

## 3. 数据模型

### 3.1 书籍清单（运行时目录）

`/api/bootstrap` 每一本 `book` 增加只读字段：

```jsonc
{
  "id": "orthodontics-7e",
  "title": "口腔正畸学",
  "edition": "第7版",
  "domain": "medicine",            // 回退默认
  "domain_label": "医学",
  "subject": "口腔正畸学",          // 回退 = title
  "resource_type": "book",         // 回退默认
  "resource_type_label": "教材",
  "sections": [ ... ],             // 稳定小节，不变
  "toc": [ ... ]                   // 权威目录，不变
}
```

### 3.2 资料学习主页（新增只读接口）

`GET /api/resource/<book_id>` 返回书籍清单 + 该书学习摘要：

```jsonc
{
  "book": { /* 同上，含 sections/toc */ },
  "summary": {
    "last_section": { "id": "...", "title": "...", "chapter_title": "...", "chapter_order": 1, "section_order": 2 },
    "last_studied_at": "2026-08-29T13:50:28+08:00",
    "last_studied_day": "2026-08-29",
    "learned_section_count": 12,
    "section_count": 74,
    "note_count": 3,
    "reading_seconds": 1511,
    "progress": 16.2
  }
}
```

字段定义全部来自真实本地记录，不虚构完成度：

- `learned_section_count`：该书的稳定小节集合中，曾被打开过**或**保存过非空笔记的去重小节数。
- `note_count`：`data/notes/` 中该书小节的非空笔记文件数。
- `reading_seconds`：`activity.json` 中按稳定小节 ID 汇总到该书的秒数。
- `progress`：`learned_section_count / section_count`。
- `last_section` / `last_studied_at`：最近一个对该书产生学习活动日期的最后阅读位置与时间；无记录时为 `null` / 空字符串。

### 3.3 阅读与练习的关联（政治资料契约）

**本轮不导入** `politics-2026` 的 MinerU 粗产物，也不把题目当 Markdown 书发布。只在本节定义未来关联契约。

推荐使用**稳定知识位置**，而不是标题模糊匹配：

```text
politics.marxism.chapter-01.section-02
        ↑domain   ↑subject   ↑章    ↑节
```

同一知识位置未来可以关联五类来源：

- 《核心考案》正文（讲义）；
- 优题库基础题；
- 基础解析；
- 拔高题；
- 拔高解析；
- 用户章节笔记；
- 错题与复习记录。

关联应保存在独立的知识位置映射（例如书籍工作区 `reports/knowledge-map.json` 或专门的知识库），不依赖正则计数认定题量。MinerU 已知问题（表格 rowspan/colspan 错位、题干与 ABCD 粘连、水印粘在选项末尾、游离数字、标题层级不可作权威目录、题数需人工复核）在得到真实样本验证并建立映射前，不得作为题库构建依据。

## 4. 兼容与迁移策略

- 稳定小节 ID：`data/notes/<section-id>.md` 笔记路径、`activity.json` 的日期/秒数/小节汇总、复习待办、日志与统计的字段语义全部不变。
- `manifest_book` 校验逻辑不放松：schema_version、`status=ready`、0 blocker、第一章起点、小节 ID 唯一性、SHA-256 校验保持不变。
- 领域字段只做**读取时的安全回退**，不要求既有包升级；新包可选写入。
- 服务版本号从 `0.9.0` 升至 `0.10.0`，`/api/health` 与 `server_version` 同步。
- 不重命名/移动现有目录；`content/`、`data/`、工作区保持原位。
- 回退：本阶段以独立 Git 提交保存在功能分支，失败可 `git reset` 回到基线标签 `yureader-v0.9.0-platform-baseline`。

## 5. 分阶段实施计划

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 一 | 领域顶层分类（医学/政治/英语）、资料学习主页、目录入口改造、默认回退、契约文档 | 本阶段完成 |
| 二 | 《核心考案》进入 YuReader（作 politics 讲义资源，含清洗与知识位置映射） | 未开始 |
| 三 | 政治题库构建（先以真实样本验证题量与结构，再做知识位置关联） | 未开始 |
| 四 | 阅读页练习入口（仅在有真实匹配题目的知识位置显示） | 未开始 |
| 五 | 昨日复习/学习日志升级为跨领域 | 未开始 |

### 接下来最小实施顺序（下一阶段）

1. 只读复核 `politics-2026` 五份产物的目录/知识位置样本，人工确定 `politics.marxism.*` 稳定位置表。
2. 《核心考案》用 YuBook 工作区构建 `politics` 讲义包（`resource_type=lecture`），先做第一章真实闭环，验证清洗与分章，再全量。
3. 建立知识位置 → 讲义页/题号/解析 的映射清单，写入工作区 `reports/`。
4. 以基础题/基础解析两册做题库样本，人工复核题号、选项粘连与答案表后，才设计题库数据结构和练习界面。

## 6. 风险与回退方式

- **风险 A：领域字段导致既有包被误判。** 回退逻辑只读取 manifest 可选字段，非法值一律回退 medicine/book，且不改写包本身；用回归测试锁定。
- **风险 B：资料学习主页改变原有“点书即展开目录”习惯。** 搜索状态仍保留内联过滤目录；浏览态点书进入学习主页，主页内含完整分层目录，可由“返回书架”回到书架，不丢位置。
- **风险 C：阅读页回归。** 阅读渲染、计时、笔记、复习、日志逻辑不改；仅书架入口与返回位置变化。浏览器按桌面/侧边栏/移动端三档验收。
- **风险 D：新接口拖慢启动或统计。** `book_learning_summary` 只扫描 `activity.json` 与笔记文件名，不读正文；`/api/resource` 仅在点开主页时调用。
- **回退方式**：功能分支上的代码可整体回退到基线标签；用户数据目录在升级期间不进入版本库，不做任何批量改写。

## 7. 验证清单（对应验收）

- `python -m py_compile app.py`、`node --check static/app.js`。
- 现有全部自动测试（应用 12/12 + YuBook 回归）。
- `/api/health` 返回 0.10.0，`/api/bootstrap` 仍返回全部 11 本医学书且 863 小节不变。
- 领域默认回退：全部现有书 `domain=medicine`、`resource_type=book`。
- 点书进入资料学习主页，`继续学习`回到上次小节；目录与章节切换、笔记与 Obsidian 逻辑、复习/日志/统计不退化。
- 深浅主题、桌面宽屏、侧边栏压缩宽度与移动端无溢出、控制台无新增错误。