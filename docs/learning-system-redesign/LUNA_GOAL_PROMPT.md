# Luna 目标模式启动提示词

## 使用方式

切换为 Luna 模型并开启目标模式后，只发送下面这一段即可。完整需求、阶段顺序、数据边界和验收标准已经写入本目录，不需要把它们再次复制进对话。

## 推荐提示词

```text
请接管 C:\Users\Yu\Documents\YuReader，并以持续目标模式完成“统一学习系统重构”。开始前依次完整阅读 AGENTS.md、README.md、docs/STATUS.md，以及 docs/learning-system-redesign/README.md 和其中链接的全部编号文档。以这些设计文档为目标方案，严格按照 05-implementation-roadmap.md 从阶段 0 顺序推进；每个阶段都要先体检、再实现、运行完整验证、更新 STATUS，并在通过 06-acceptance-and-regression.md 对应门槛后才进入下一阶段。保护所有现有书籍、题库、笔记、学习数据和 Obsidian 文件，不清理原始资料，不接入模型 API，不重做视觉系统，不把多个阶段一次性混改。先简短报告当前基线和阶段 0 的最小范围，然后直接开始。
```

## 模型执行约束

提示词已经要求模型读取完整文档，因此后续不应再发送长篇需求。只有发生下列情况才需要用户介入：

- 需要删除或覆盖无法恢复的用户数据；
- 现有未提交修改与当前阶段直接冲突且无法安全区分；
- 设计文档之间出现无法通过真实代码和数据判断的重大冲突；
- 需要修改 OneDrive 原始资料或引入新的外部服务。

普通实现选择、测试修复和兼容处理由目标模式自行完成。

## 中断后恢复提示词

若目标模式中断，使用：

```text
继续 YuReader 统一学习系统重构。先读取当前 goal、git 状态、docs/STATUS.md 和 docs/learning-system-redesign/05-implementation-roadmap.md，确认上一个已通过验收的阶段与当前未完成阶段；不要重做已完成工作，从当前阶段最近的安全检查点继续，仍按 06-acceptance-and-regression.md 验收。
```

