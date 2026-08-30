# YuPractice 协作说明

YuPractice 是 YuReader 内部孵化的极轻量题库数据地基：只定义“正式题库发布包”的数据契约、验证命令与自动隔离规则。它让后续 Agent 产出的基础题、拔高题能被统一、确定性地验证。**不是答题界面，不做发布，不导入真实题库，不处理 PDF/OCR/模型。**

## 必须先读

每次开始前完整阅读：

1. `README.md`
2. `schema/question-bank.schema.json`
3. `examples/minimal-valid/` 与 `examples/invalid/`（两者共同说明“通过”与“必须失败”的边界）
4. `tests/test_yupractice.py`（每条规则都有隔离测试）
5. `C:\Users\Yu\Documents\YuQuiz\AGENTS.md` 与 `README.md` 只读参考，理解已验证的六条原则（见本文末尾），但不复制其业务、不依赖其 `study.db`。

## 任务边界

- 只新增到 `tools/yupractice/`；不修改 YuReader `app.py`、`static/index.html`、`static/app.js`、现有 UI、正式 `content/` 或用户 `data/`。
- 不修改 YuQuiz；不迁移、不复制其 `study.db` 与运行数据。
- 不导入真实题库、不做原子发布、不修改正式书架。
- 当前工作树可能已有其他未提交修改，必须保留；不要 `git reset/clean/checkout` 覆盖。
- 不引入大型框架、数据库服务、前端、任务队列或模型 API；工具只用 Python 标准库。

## 核心判断责任

- **Agent 负责判断**，这是本工具的默认工作方式。用户不参与人工内容复核。
- **不确定 OCR 优先保留或隔离**：宁可在 `quarantine/questions.jsonl` 中保留原文待复核，也不要自动“猜测”成正式题。隔离不是失败，是诚实。
- **禁止大规模重写**：题干、选项、解析只允许小块、可追溯的修复；不许无依据地全书替换。
- **目录和知识位置优先**：先定 `knowledge-map.json`（稳定知识位置），再定 `source-index.json`（块级出处），最后才写题目。不要用脆弱正则从标题“算”出题量或位置。
- **正式发布必须无 blocker**：`quality.blocker_count == 0` 且 `status == 'pass' 或 'warning'`（warning 由 Agent 自行解释）。有 blocker 时先修复，不许靠放宽规则“通过”。
- **原书解析与个人解析严格分离**：`source_analysis_md`、`distractor_analysis_md` 是**不可变发布内容**；个人解析、作答历史、用户笔记是用户数据，**绝不写进题库包**，也不得覆盖原书解析。
- **所有内容必须可追溯**：每题至少一条 `source_refs`（source_id + block_id）能在 `source-index.json` 解析；每条 `transformation` 必须有 `type` 和 `reason`；隔离题必须有 `reasons.json` 记录。
- **工具不负责 PDF/OCR 或模型调用**：`yupractice.py` 只校验结构化包；原始教材的识别、清洗、语义判断由 Agent/其他管线完成后再来验证。

## 验证与发布流程

```powershell
python tools\yupractice\yupractice.py validate <题库包目录> [--json]
```

- blocker 存在 → 退出码 `2`，不可发布。
- 只有 warning、无 blocker → 退出码 `0`，可通过；warning 是 Agent 必须自行解释的自动观察项，不要求用户复核。
- 每次 validate 生成 `reports/validation.json` 与 `reports/quality-report.json`（派生报告，不参与哈希）。

发布门禁（由 Agent 自行执行；本工具不发布）：`bank.status == ready`、全部正式题 `status == ready`、0 blocker、manifest.quality 与实测一致、隔离区不泄漏到正式区。

**跨文件身份一致性（新增门禁，必须为 blocker）**：`manifest.bank.id` 必须与 `knowledge-map.json.bank_id`（E039）、`source-index.json.bank_id`（E040）、`quarantine/reasons.json.bank_id`（E041）一致；正式题/隔离题若携带 `bank_id` 字段，也必须与 `manifest.bank.id` 一致（E042/E043）。

**source-index / knowledge-map 结构完整性（新增门禁）**：`index_version`/`map_version` 必须为当前支持版本 1（E038/E054）；`sources`/`entries` 必须是数组；`source_id` 非空且全局唯一、`block_id` 非空且同 source 内唯一、`start_line <= end_line`、行号为正整数、`page`/`page_label` 类型合理；缺少 `source_id`/`block_id` 等字段边界错误一律记录为 blocker，绝不允许 KeyError/异常退出，验证器必须继续收集其他问题并一次返回完整报告。

**不崩溃原则**：验证器在字段边界显式校验常见类型错误并转为 findings；禁止用覆盖全程序的宽泛 except 掩盖代码错误。

**Windows 中文输出**：CLI 只对交互式 Windows 控制台安全 idempotent 地配置 UTF-8；不改变重定向输出与非 Windows 环境；`--json` 始终输出合法 UTF-8 JSON（可被 `json.loads` 重新加载）。

## 质量态度

- 先让 `examples/invalid` 失败、`examples/minimal-valid` 通过，作为工具自身的回归基线。
- 新增规则必须先有对应的最小测试；不能只为了某一个示例而加宽规则。
- 报告如实反映 blocker/warning 数量；不要声称“已清零”而测试仍在报警。
- 不要在文档或报告中把尚未实现的发布、导入、答题能力写成现有功能。