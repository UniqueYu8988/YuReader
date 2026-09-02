# YuReader 学习系统数据恢复说明

本说明用于统一学习系统重构后的数据恢复。YuReader 不会用恢复副本覆盖用户资料；恢复动作应在确认目标范围后手工执行。

## 阶段 7 恢复副本

副本位于仓库外：

```text
C:\Users\Yu\Documents\YuReader-stage7-backups\YuReader-stage7-backup-20260902.zip
```

覆盖范围：

- `data/`
- `content/`
- `question-banks/`
- 完整 `C:\Users\Yu\OneDrive\图片\Atlas\个人笔记\Obsidian Vault`

文件包含 4,782 个条目，压缩包 CRC 校验通过。SHA-256：

```text
260e31e4a51886568bf5400a9a394d2e61a17fd9b840caae38c518dc5efff395
```

## 恢复步骤

1. 停止正在运行的 `python app.py` 或 `启动 YuReader.bat`。
2. 把当前 `data/`、`content/`、`question-banks/` 和 Obsidian Vault 复制到另一个备份目录；不要先删除当前目录。
3. 用 `Get-FileHash -Algorithm SHA256` 核对 ZIP 哈希，确认与上面的值一致。
4. 先解压到临时目录，检查其中的四个根目录，再只复制需要恢复的根目录或具体文件。
5. 重新启动 YuReader，检查 `/api/health`、书架、记录页和 Obsidian 文件；确认无误后再处理临时目录。

PowerShell 示例：

```powershell
$backup = 'C:\Users\Yu\Documents\YuReader-stage7-backups\YuReader-stage7-backup-20260902.zip'
Get-FileHash -Algorithm SHA256 -LiteralPath $backup
$restore = 'C:\Users\Yu\Documents\YuReader-stage7-restore-check'
Expand-Archive -LiteralPath $backup -DestinationPath $restore -Force
Get-ChildItem -LiteralPath $restore
```

解压后的 `data/`、`content/` 和 `question-banks/` 对应 YuReader 项目根目录；`Obsidian Vault/` 对应原 Vault 的上级快照目录。不要把 `Obsidian Vault/` 的内容混复制到 YuReader 项目中。

## 保护原则

- 新版每日记录位于 `data/learning-records/YYYY/MM/`，旧 `data/logs/`、`data/review-workflow/`、旧周报和每日复习文件保留为只读历史。
- 恢复旧历史不会删除新的统一记录；如需回退，先保存当前 `data/learning-records/` 和 `data/activity.json`。
- 不要用脚本批量重命名稳定小节 ID，不要覆盖 `data/notes/` 中无法确认归属的笔记，也不要改写 `content/` 或 `question-banks/` 的发布包来修复记录显示。
