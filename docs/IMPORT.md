# Markdown 导入闭环

YuReader 0.4.0 使用“工作区构建 → 正式目录编排 → 结构检查 → 原子发布”的最小流程。原始输入和外部 Agent 产物只读，所有复制件和派生结果写入项目目录。正文无需被统一清洗到完美状态，重点是忠实保留内容并建立可靠阅读边界。

## 目录边界

```text
workspace/<book-id>/
  manifest.json                   稳定 ID、目录、顺序、来源和质量状态
  original/source.md              原始输入的本地归档副本
  raw/agent-cleaned-candidate.md   既有清洗候选，不等于正式正文
  raw/agent-process-result.json    外部处理记录
  cleaned/chapters/*.md            章节级正文
  cleaned/pages/*.md               按正式目录生成的小节页面
  slices/README.md                 未来能力预留，本阶段不生成切片
  reports/quality.json             内容质量报告
  reports/layout.json              目录映射与页面长度报告

content/<book-id>/
  manifest.json
  cleaned/chapters/*.md
  cleaned/pages/*.md
  reports/*
```

`content/` 只包含发布所需副本。发布先写临时目录，构建或目录映射失败不会替换已有书籍包。再次导入相同 `book-id` 时，章节和小节 ID 由书籍 ID、章序和节序确定，不依赖文件时间或标题字符偏移。

## 《口腔正畸学》第7版

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「正畸」第7版.md" `
  --candidate-run "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「正畸」第7版_agent_output\run_20260823_165627" `
  --book-id orthodontics-7e `
  --title "口腔正畸学" `
  --edition "第7版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\orthodontics-7e.json" `
  --publish
```

导入器首先核对外部处理记录声明的原始 SHA-256，再依据 layout 中明确复核过的目录标题拆分正文；对于原文中没有 Markdown 标题但需要独立承载的确定内容（例如完整 HTML 表格），layout 可使用唯一内容锚点分页。目录标题/锚点缺失、重复或逆序会阻断发布；超过 8,000 字的正式目录小节只进入长度报告，本阶段不机械切断。

《口腔正畸学》第7版目前形成16个目录分组、75个学习小节，平均约4,007字。提要归入本章第一节，思考题和参考文献归入最后一节；书目信息和原书目录仍保留在工作区，但不重复进入阅读目录。

## 直接从原始 Markdown 建书

没有外部 Agent 候选时，省略 `--candidate-run`。layout 除章名、章节文件和小节标题外，还需为每章提供人工复核的 `source_line_start` 与 `source_heading`。导入时会同时校验行号、标题文字和章节顺序；任一不符都会阻断构建。

layout 可以包含少量 `reviewed_replacements`，但只能记录该书逐条核对过的完整词组，不允许把单字符全局替换冒充通用规则。扫描水印、公众号、分卷标记及同章重复页眉只在派生候选中移除；无论水印是否单独成行或粘在页眉后，原始归档都保持不变，所有变化写入 `raw/import-process-result.json`。

正式阅读边界固定为第一个可靠的“第一章”：第一章以前的书目信息、前言、目录和其他前置内容不写入 `content/<book-id>/` 的正式目录，只在 `workspace/` 归档和来源映射中保留。目录文件本身是整理参考，不会被当作正文页面；无法识别第一章时导入失败闭合。

目前共享的确定性清洗使用 `tools/occlusion_terms.json` 中的“𬌗”标准术语表。导入器从完整标准词自动派生“验、骑、矜、雅、酷、牙合、体验”等 OCR 形态，例如“验面 → 𬌗面”“上骑架 → 上𬌗架”“体验支托 → 𬌗支托”；绝不全局替换单个字符，因此“实验、试验、经验、检验、骑跨、优雅、体验、咬合”保持原样。

词典同时覆盖牙体牙髓常见的窝洞预备组合词，例如“邻𬌗洞、邻𬌗邻洞、𬌗壁、𬌗轴线角、颊(腭)𬌗洞”；这类完整词组的“验/矜/雅/酷”变体可安全归一化，仍不会触碰孤立的“验、合、咬”。

词典还单独记录𬌗完全丢失的形态。“错畸形、覆覆盖”等结构唯一的情况可以自动补字；“前牙开、后牙反、组牙功能、对牙”等有合法省称或普通语句可能的情况只检测不改写。详细边界见 [OCCLUSION_TERMS.md](OCCLUSION_TERMS.md)。新书可先运行 `python tools/audit_occlusion_terms.py --source "书籍.md"` 查看候选，不修改源文件，也不要求用户建立逐条人工复核清单。质量报告中的非阻断项只是后续规则升级的自动观察数据。

《口腔种植学》第5版：

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「种植」第5版.md" `
  --book-id implantology-5e `
  --title "口腔种植学" `
  --edition "第5版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\implantology-5e.json" `
  --publish
```

当前结果为12章、48个正式“节”级页面，平均3,386字。原始文件5123行保持不变；派生候选移除53行明确的扫描元数据，按8条书籍专用完整词组规则修复14处方框字符，并按共享专业词典恢复109处“𬌗”。3页超过8,000字，只进入长度报告，不机械拆页。

《口腔解剖生理学》第8版：

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「口解」 第8版.md" `
  --book-id oral-anatomy-8e `
  --title "口腔解剖生理学" `
  --edition "第8版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\oral-anatomy-8e.json" `
  --publish
```

本书采用原始 Markdown 直入：12个目录分组、156个阅读页，正文章节、三组实验附录和中英文索引分开编排。清洗只移除确定的水印/公众号/重复页眉，按共享词典恢复503处完整𬌗术语，并留下27条高置信度缺字处理记录（实际补回31个𬌗字符，包含“影响建”“萌出建”“正中关系建”等固定句式）；发布正文不再残留“验、骑、矜、雅、酷、牙合”替代词。质量报告为 `warning` 但无阻断，13个方框字符、48个 LaTeX 片段和9个仅检测缺字候选保留为自动观察项；唯一超过8,000字的是索引 K 段（9,758字），不属于正文学习页。

《口腔组织病理学》第8版（口组）：

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「口组」第8版.md" `
  --book-id oral-pathology-8e `
  --title "口腔组织病理学" `
  --edition "第8版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\oral-pathology-8e.json" `
  --publish
```

本书没有可复用的 Agent 产物，采用 source-only reviewed layout：24个目录分组、192个阅读页，发布正文441,201字，章节顺序和来源行号均写入 manifest。派生候选移除235行水印/页眉粘连行，按共享词典归一化23个确定性完整术语，发布正文恢复22个𬌗字；“对牙”两处仅检测不自动改写。质量报告为 `warning` 但无阻断；正文学习页均未超过8,000字，唯一超阈值页是参考文献（8,017字），2个方框字符、86个 LaTeX 片段和11个“×线”疑似 OCR 作为自动观察项保留。

《口腔修复学》第8版（修复）：

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「修复」第8版.md" `
  --book-id prosthodontics-8e `
  --title "口腔修复学" `
  --edition "第8版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\prosthodontics-8e.json" `
  --publish
```

本书先检查了 Agent 最新完整轮次 `run_20260824_010425`，但该轮把8个复杂表格改为编号列表并重写了大量标题层级，因此没有冒充正式正文。最终从原始 Markdown 直入，建立11个目录分组、208个阅读页，发布正文483,869字；第3章按源文件第1182行的真实“牙体缺损的修复”标题起算，第10章按29个实习项目分页，附录按可识别字母分页。候选记录1,299条变换，原始 SHA-256 为 `04c43b00d715baee995e45c30c585b7db31c6da823770a2e54ab1fda5cee8446`。

质量报告为 `warning` 但无阻断，230项自动观察项主要是原始 OCR 标题、方框字符、LaTeX 和仅检测缺字候选；唯一超过8,000字的是单独保留的“牙列检查表” HTML 表格（14,475字）。该表格在真实页面中保持跨行/跨列结构，没有转成列表或拆坏原文。正式产物位于 `content/prosthodontics-8e/`，完整审计与来源映射位于 `workspace/prosthodontics-8e/`。

《牙体牙髓病学》第5版：

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「牙体牙髓」第5版.md" `
  --book-id dental-pulp-5e `
  --title "牙体牙髓病学" `
  --edition "第5版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\dental-pulp-5e.json" `
  --publish
```

本书没有可复用的 Agent 产物，采用 source-only reviewed layout：排除书前绪论后，以第一章至中英文索引共30个正式目录分组、184个阅读页，依原书节级目录分页，实验教程按实习项目并在必要处按自然小标题分页。正文学习页均低于8,000字，最长7,890字。派生候选清理固定水印和重复章页眉，归一化完整“𬌗”专业词组；33个 HTML 表格保持原结构。正式产物位于 `content/dental-pulp-5e/`，完整来源映射和质量报告位于 `workspace/dental-pulp-5e/`；书前绪论只保留在原始归档和来源证据中。

《牙周病学》第5版：

```powershell
python tools/import_markdown.py `
  --source "C:\Users\Yu\OneDrive\图片\Book\「口腔医学」教材\「牙周」第5版.md" `
  --book-id periodontology-5e `
  --title "牙周病学" `
  --edition "第5版" `
  --layout "C:\Users\Yu\Documents\YuReader\layouts\periodontology-5e.json" `
  --publish
```

本书未发现可复用的 Agent 产物，采用 source-only reviewed layout：排除书目信息、前言、目录后，以第一章至中英文索引共22个正式目录分组、361个阅读页，依原书节级目录分页；长节只在自然小标题或完整 HTML 表格边界处拆分。派生候选记录313条变换，移除确定的水印/重复页眉，按共享词典归一化210个完整“𬌗”替代词并补回7个高置信度缺失“𬌗”，正文发布约514,355字；书前单元只保留在原始归档和来源证据中。

质量报告为 `warning` 但无阻断；已知“𬌗”替代词、水印和分卷标记均为0。74个方框字符、196个 LaTeX 片段、12个“×线”疑似 OCR 和5个仅检测缺字候选保留给上下文理解。唯一超过8,000字的是完整“牙周检查记录表（1）”HTML 表格（13,068字），保持原表格结构，不机械拆分。正式产物位于 `content/periodontology-5e/`，完整来源映射和质量报告位于 `workspace/periodontology-5e/`。

《口腔颌面外科学》第8版的既有 YuReader 包已使用 `tools/migrate_first_chapter.py` 做边界迁移：排除书前资料后保留第一章至附录/索引的21个正式分组、320个阅读页。迁移只更新运行时 manifest、顺序和报告，保留稳定 ID、来源行号与正文字节；报告位于 `content/oral-maxillofacial-surgery-8e/reports/content-boundary.json`。原始文件、Agent 产物和历史 `AI-Book` release 均不覆盖。

## Manifest 要点

- `book.id`：稳定、可读的书籍 ID。
- `book.status`：只有 `ready` 会被正式书架加载。
- `provenance`：原始路径、归档路径、候选来源模式、处理记录和 SHA-256。
- `toc[]`：书籍正式目录的章级分组及小节顺序。
- `sections[].id/order`：稳定小节 ID 和全书阅读顺序。
- `sections[].chapter_id/section_order`：所属章节和章内顺序。
- `sections[].artifact/material_kind`：实际小节页面及其正文类型。
- `sections[].source_map`：清洗章节行号、候选章节和原始归档位置。
- `source_chapters[]`：进入目录编排前的章节级派生文件。
- `quality` 与 `reading_layout`：内容质量和目录结构摘要。

`/api/bootstrap` 返回完整目录树和扁平阅读顺序；`/api/sections/<id>` 返回小节正文、章节位置、来源映射和本地笔记。
