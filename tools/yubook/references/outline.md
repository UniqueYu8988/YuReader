# 权威目录与页面计划

`outline.json` 同时保存权威目录树和阅读页面计划，但两者职责不同：`nodes` 描述原书结构，`pages` 描述 YuReader 一次展示多少正文。

## 最小结构

```json
{
  "schema_version": 1,
  "book": {
    "id": "example",
    "title": "书名",
    "edition": "第1版",
    "identity_evidence": [
      {"field": "title", "line": 5, "quote": "书名"},
      {"field": "edition", "line": 18, "quote": "第1版"}
    ]
  },
  "source": {
    "artifact": "source/original.md",
    "sha256": "...",
    "line_count": 1000
  },
  "content": {"start_line": 120, "end_line": 1000},
  "cleaning": {
    "text_replacements": [
      {"line": 420, "old": "完整错误词组", "new": "完整正确词组", "count": 1, "reason": "目录与正文互证"}
    ]
  },
  "nodes": [
    {
      "id": "ch01",
      "parent_id": null,
      "order": 1,
      "kind": "chapter",
      "title": "第一章 绪论",
      "source_line": 120
    },
    {
      "id": "ch01-s01",
      "parent_id": "ch01",
      "order": 1,
      "kind": "section",
      "title": "第一节 学科概况",
      "source_line": 124
    }
  ],
  "pages": [
    {
      "id": "ch01-s01",
      "node_id": "ch01-s01",
      "order": 1,
      "role": "reading",
      "title": "第一节 学科概况",
      "start_line": 120,
      "end_line": 300
    }
  ],
  "issues": []
}
```

所有行号为 1-based 且两端包含。

## 节点类型

- `chapter`：原书正式章；必须从第一章开始并连续。
- `section`：原书“节”，通常是默认阅读页。
- `topic`：一、二、三或更低层级的真实主题；只有父节过长时才独立分页。
- `supporting`：思考题、参考文献、实习、附录、索引等非主学习结构。

`parent_id` 表达真实父子关系。不要用标题中的圆点、破折号或重复“第一节”模拟层级。

## 页面角色

- `reading`：进入书架日常阅读顺序。
- `reference`：保留在数据包中，但不进入主要学习目录。

从 `content.start_line` 到 `content.end_line` 的每一行必须被一个页面覆盖一次。不能用删除范围掩盖正文缺失。若书末索引不进入学习目录，仍建立 `reference` 页面保存它。

## 分页判断

- 优先一节一页。
- 8000字不是分页上限。默认保持一个自然“节”为一页，以维护完整知识单元和笔记归属。
- 自然节超过约30000字时才检查拆分；优先使用“一、二、三”等完整主题边界。没有可靠边界时宁可保留完整页面。
- 内容提要通常并入本章第一节；思考题、参考文献、附录和索引默认标记为 `reference`，完整保留但不占用日常阅读顺序。若某类 supporting 材料确实是本书的核心学习单元，可设为 `reading`，但页面必须填写 `reading_reason` 说明依据。
- “篇、编、单元”等正文分卷标题若紧邻下一章之前，应随下一章的首个阅读页保留，不能因为它位于上一章参考文献之后而被归入上一章的 reference 页面。此类标题可以不成为独立导航节点，但其页面归属必须符合语义方向。
- 表格、公式、图片与图注不能跨页拆坏。
- 页面标题必须是完整语义标题，不得使用提示句、治疗标签、单个索引字母或正文残片。
- 正式导航中的“第X章”“第X节”“实验X”与后续标题之间统一保留一个半角空格。OCR 原文缺少或混入多余空格时，应规范导航标题并保留 `source_title` 与修复证据；不要让同一本书的目录同时出现“第一节标题”和“第一节 标题”。

## 证据优先级

1. 清晰的原书目录；
2. 正文中重复出现且顺序可靠的章、节标题；
3. 章节开头的内容提要或结构说明；
4. 页眉和 OCR Markdown 标题只能作为弱证据。

目录本身有 OCR 缺失时，应使用正文补全；正文标题误升时，应服从已经互证的目录树。

## 身份与标题修复

- 文件名、下载站标题和扫描包名只是弱证据；书名与版次必须引用书内扉页、版权页等原文行。
- 同名书已经进入 YuReader 时，升级包复用现有稳定书籍 ID，避免产生重复书和割裂笔记关联。
- 只修复导航标题而不改正文时，在节点记录 `source_title` 与 `title_normalization`（原因和证据行）。构建包会分别保存规范标题、运行时标题与完整 breadcrumb。
- YuReader 当前按章展示扁平页面列表。topic 独立分页时，构建器会将父节与 topic 组合为运行时标题，避免“一、二、三”脱离语境。

## 派生正文清理

- `source/original.md` 永不修改。构建器只在物化页面时移除已知的水印 Markdown 标题，并在 `reports/transformations.json` 记录原文行和变换。
- 其他修复必须使用 `cleaning.text_replacements` 指定来源行、完整旧词组、完整新词组、出现次数和原因。禁止全局单字替换。
- 目录修复与正文修复分开：导航错字使用节点的 `title_normalization`；只有会影响阅读或侧边栏理解的高置信正文词组才进入 text replacements。
- 导航已经修正的确定性专业错字仍需检查派生正文，尤其是正文第一页保留的章、节标题。只修导航而让阅读页继续显示“睡液腺”“聂下颌关节”等确定性错字，不算完成。
