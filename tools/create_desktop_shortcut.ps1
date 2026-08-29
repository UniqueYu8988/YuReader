[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$ShortcutName = 'YuReader.lnk',
    [string]$DesktopPath = [Environment]::GetFolderPath('Desktop')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$nativeLauncher = Join-Path $project 'YuReader.exe'
if (Test-Path -LiteralPath $nativeLauncher -PathType Leaf) {
    $launcher = $nativeLauncher
} else {
    $launcherItem = Get-ChildItem -LiteralPath $project -File -Filter '*.bat' |
        Where-Object { $_.Name -like '*YuReader*.bat' } |
        Select-Object -First 1
    if ($null -eq $launcherItem) {
        throw "YuReader launcher not found in: $project"
    }
    $launcher = $launcherItem.FullName
}

$shell = New-Object -ComObject WScript.Shell
$iconAsset = Join-Path $project 'static\assets\yureader-shortcut.ico'

function New-YuReaderShortcut {
    param([string]$Path)

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $launcher
    $shortcut.WorkingDirectory = $project
    $shortcut.Description = 'Launch local YuReader reader'
    $shortcut.WindowStyle = 7
    if (Test-Path -LiteralPath $iconAsset -PathType Leaf) {
        $shortcut.IconLocation = "$iconAsset,0"
    } else {
        $iconPath = Join-Path ([Environment]::GetFolderPath("Windows")) "System32\shell32.dll"
        $shortcut.IconLocation = "$iconPath,167"
    }
    $shortcut.Save()
    Write-Output "Created: $Path"
}

$desktop = (Resolve-Path -LiteralPath $DesktopPath).Path
$startMenu = [Environment]::GetFolderPath('StartMenu')
$destinations = @(
    (Join-Path $desktop $ShortcutName),
    (Join-Path (Join-Path $startMenu 'Programs') $ShortcutName)
)

foreach ($destination in $destinations) {
    New-YuReaderShortcut -Path $destination
}

Write-Output "Target:  $launcher"
