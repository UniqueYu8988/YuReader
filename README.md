# YuReader

YuReader 是一个面向 Markdown 书籍的本地 AI 阅读器底座。它从 YuQuiz 0.1.1 的真实界面体系分支出来，保留已经验证过的字体、暖色纸张、细线分隔、章节阅读工具条、侧边栏折叠、深浅色主题、克制动效和笔记浮窗；题库、答题、模拟考试与统计业务均未带入。

## 当前能力

- 读取 `content/` 下的普通 Markdown，也可读取带稳定 ID、来源映射和质量状态的发布包。
- 书架支持搜索，并可展开书籍直接选择章节。
- 首页整合继续阅读、今日学习轨迹、快捷入口和最近书目；“当前阅读”不再占用独立导航，阅读页与完整目录统一归入“书架”。
- “统计”展示今日/累计阅读时长、笔记覆盖、活跃天数、连续学习、近12周时长热力图和分书笔记分布；这些数据只来自本地阅读计时和实际笔记文件，不推断读完进度。
- 正式目录可作为权威编排来源，形成“书籍 → 章 → 小节”的阅读层级。
- 正式阅读正文统一从第一个“第一章”开始；版权页、前言、目录等前置内容只保留在归档和来源证据中，不进入书架阅读页。
- 当前章节可以直接被浏览器侧边栏 AI 读取和总结。
- 清洗正文与本节笔记分开查看，章节之间可以前后切换。
- 笔记输入框自动保存到本地 `data/notes/`，不依赖外部 AI API。
- “复习”入口直接按文件保存日期读取前一天的原章节笔记，并按书目/学科铺成待办；每项显示笔记数、字数和该书实际阅读时长，进入后集中呈现该学科昨日笔记。
- 章节笔记继续按稳定小节 ID 原地保存在 `data/notes/`，不会为复习复制正文或生成每日内容快照。
- Gemini 的分科复习成果粘贴回网页后完成对应待办；全部完成后，可用合并 Markdown 生成一段“昨日总结”，它会置于当天唯一一份学习日志开头。检测到 Obsidian 时保存到 `YuReader/学习日志/YYYY-MM-DD.md`，否则回退到 `data/logs/YYYY-MM-DD.md`。
- “日志”入口像邮件列表一样回看每日归档；“生成周报”仅收集一周的每日总结，阶段总结独立保存到 Obsidian 的 `YuReader/周报/YYYY-Www.md` 或本地 `data/weekly-reports/`，不会重复搬运所有章节笔记。
- Markdown 表格与带 `rowspan` / `colspan` 的受限 HTML 表格可在正文中阅读。
- 导入工作区将原始归档、清洗候选、发布正文、质量报告和未来语义切片分开保存。
- 没有外部 Agent 产物时，可直接用原始 Markdown 与人工复核的 layout 建立可追溯书籍包。
- 直接导入会安全归一化口腔教材中“𬌗”的稳定 OCR 词组，不会全局替换“验”或要求逐条人工审校普通扫描噪声。
- [“𬌗”专业术语对照表](docs/OCCLUSION_TERMS.md)区分完整词组替代、𬌗完全丢失、仅检测候选和必须保留的合法词；导入前可用 `tools/audit_occlusion_terms.py` 只读扫描新书。

## 启动

```powershell
python app.py
```

然后打开 <http://127.0.0.1:8775>。也可以双击 `启动 YuReader.bat`。

桌面快捷方式 `YuReader.lnk` 会调用项目内的轻量原生启动器 `YuReader.exe`（它再复用现有 `启动 YuReader.bat`，不产生第二套启动逻辑）；重建脚本会同时写入桌面和开始菜单的“所有应用”列表。若快捷方式不存在或项目目录发生变化，可运行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/create_desktop_shortcut.ps1
```

随后可在“开始”→“所有应用”→“YuReader”上右键选择“固定到开始屏幕”。

启动器源码位于 `tools/launcher/`；若需重建原生入口，可运行 `dotnet publish tools/launcher/YuReaderLauncher.csproj -c Release -p:PublishAot=true -o tools/launcher/publish`，再将生成的 `YuReader.exe` 放回项目根目录。

把书籍 Markdown 放入 `content/` 后刷新书架即可。内容、章节笔记、学习日志和周报默认只保存在本机与用户自己的 Obsidian vault。学习活动仅将日期、稳定小节 ID、阅读秒数、打开次数和保存状态写入 `data/activity.json`，不复制书籍正文或笔记内容。新版计时会额外按稳定小节 ID 汇总每日时长，供复习待办精确折算到书目；旧记录无法可靠反推时显示“暂无记录”。

导入规则：YuReader 只展示从原书第一个可靠“第一章”标题开始的章节。书籍信息、版权页、前言和目录等第一章以前的内容不会进入正式书架，但仍保留在 YuBuilder/YuReader 工作区的原始归档和来源映射中；没有可识别第一章的包不会被加载。

已有运行时包可用 `python tools/migrate_first_chapter.py --root content --apply` 做同样的原子边界迁移；迁移报告写入各书包的 `reports/content-boundary.json`，不会改写原始文件或历史发布包。

## 阅读时长与本地接口

计时只在章节阅读页处于前台时运行。进入章节后开始；离开阅读页或浏览器转入后台立即暂停；连续10分钟没有滚动后暂停，重新滚动后恢复。前端约每15秒写入一次增量，因此外部查询最多有一个心跳周期的延迟。

其他本机软件可以读取：

```text
GET http://127.0.0.1:8775/api/reading-time
GET http://127.0.0.1:8775/api/reading-time?date=2026-08-24
GET http://127.0.0.1:8775/api/reading-time?days=30
```

响应提供秒数、分钟数、最后写入时间和可选历史数组。服务只监听本机地址；计时记录仍保存在 `data/activity.json`，不包含正文或笔记内容。

## 可追溯 Markdown 导入

真实书籍不要直接复制进正式书架。使用 `tools/import_markdown.py` 先在 `workspace/<book-id>/` 构建，再通过可复核的 layout 将正式目录映射到正文，最后使用 `--publish` 原子发布。导入器既支持已有外部 Agent 候选，也支持直接从原始 Markdown 按复核过的原文行与标题建书；目录映射失败不会污染 `content/`。

《口腔正畸学》第7版和《口腔种植学》第5版的实际导入命令、manifest 字段和目录边界见 [docs/IMPORT.md](docs/IMPORT.md)。

## 设计边界

YuReader 暂不内置模型调用。侧边栏 AI 负责阅读当前页面、总结、问答、分科复习与阶段总结，YuReader 只负责组织可读上下文、记录待办状态和原子保存。AI 内容不会写入原书正文；学习日志、周报与章节笔记彼此分开，章节笔记仍按现有本地机制保存。

## UI 继承关系

- `static/styles.css`：直接继承自 YuQuiz 的设计系统基础文件。
- `static/vendor/lucide.min.js` 与 `static/assets/`：复用 YuQuiz 的图标与品牌素材。
- `static/reader.css`：仅保留阅读器专用的少量组合规则，不重写 YuQuiz 的基础组件。
- `static/index.html` 与 `static/app.js`：阅读器自己的最小页面骨架和业务逻辑。
