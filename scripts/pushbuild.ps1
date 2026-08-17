# OpenCompanion 一键推送 + 触发 Docker 构建 / 清理缓存与用户数据
# 用法:  powershell -ExecutionPolicy Bypass -File pushbuild.ps1
# 建议直接双击 run_pushbuild.bat 使用

param(
    [ValidateSet("menu", "push", "cache", "data")]
    [string]$Action = "menu"
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 定位项目根（脚本放在 scripts/ 下 → 根 = 上级目录）
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root ".git"))) { $Root = $PSScriptRoot }
Set-Location $Root

$ExcludeFile = Join-Path $Root ".pushignore"
$GitDir      = Join-Path $Root ".git"

# 默认候选文件：含密钥/个性的文件，推送前逐个确认是否更新
$CandidateFiles = @(
    "config.ini",
    "MCP/OB/.env",
    "MCP/OB/config.yaml",
    "prompt.txt",
    "prompt_extra.txt"
)

function Write-Head($t) {
    Write-Host ""
    Write-Host ("=" * 56) -ForegroundColor DarkCyan
    Write-Host ("  " + $t) -ForegroundColor Cyan
    Write-Host ("=" * 56) -ForegroundColor DarkCyan
}

function Get-Excludes {
    if (-not (Test-Path $ExcludeFile)) { return @() }
    @(Get-Content $ExcludeFile -Encoding UTF8 |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") } |
        Sort-Object -Unique)
}

function Add-Exclude([string]$p) {
    $list = @(Get-Excludes)
    if ($list -contains $p) { return }
    Add-Content $ExcludeFile ("# " + (Get-Date -Format "yyyy-MM-dd HH:mm") + " 手动排除`n" + $p) -Encoding UTF8
}

function Remove-Exclude([string]$p) {
    $lines = @(Get-Content $ExcludeFile -Encoding UTF8)
    $out = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if (($lines[$i].Trim() -eq $p) -or
            ($lines[$i].Trim() -eq $p) -or
            ($lines[$i - 1].EndsWith("手动排除") -and $lines[$i].Trim() -eq $p) -or
            (($lines[$i].Trim() -eq $p))) {
            if ($i -gt 0 -and $lines[$i - 1].Trim().EndsWith("手动排除")) {
                [void]$out.RemoveAt($out.Count - 1)
            }
            continue
        }
        [void]$out.Add($lines[$i])
    }
    Set-Content $ExcludeFile $out -Encoding UTF8
    Write-Host "  已从排除列表移除: $p" -ForegroundColor Yellow
}

# ---- 项目缓存清理（__pycache__ / *.pyc / pytest / build 等）----
function Clear-Cache {
    Write-Head "清理项目缓存"
    $excludeRoots = @($GitDir, "runtime", ".venv", "$Root\TTS")
    $dirNames = @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", "build", "dist")
    $removed = New-Object System.Collections.ArrayList

    Get-ChildItem $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in $dirNames -and -not $_.FullName.Contains("\.git\") } |
        ForEach-Object {
            if ($_.FullName -like "\*.venv*" -or $_.FullName -like "*runtime*") { return }
            [void]$removed.Add($_.FullName)
            try { Remove-Item $_.FullName -Recurse -Force -ErrorAction Stop } catch { }
        }

    $pycCount = 0
    Get-ChildItem $Root -Recurse -File -Filter "*.pyc" -Force -ErrorAction SilentlyContinue |
        Where-Object { -not $_.FullName.Contains("\.git\") } |
        ForEach-Object {
            if ($_.FullName -like "*runtime*" -or $_.FullName -like "*.venv*") { return }
            $pycCount++
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        }

    Write-Host "  已删除缓存目录: $($removed.Count) 个, .pyc 文件: $pycCount 个" -ForegroundColor Green
}

# ---- 用户数据清理（data / conversation / logs / OB 记忆 / 微信会话）----
function Clear-Data {
    Write-Head "清理用户数据"
    $targets = @(
        @{ name = "对话/事件/用户档案"; dir = "$Root\data" },
        @{ name = "上下文存档";          dir = "$Root\conversation" },
        @{ name = "运行日志";            dir = "$Root\logs" },
        @{ name = "OB 长期记忆";         dir = "$Root\MCP\OB\buckets" },
        @{ name = "微信登录会话(需重扫码)"; dir = "$env:USERPROFILE\.weilink" }
    )
    foreach ($t in $targets) {
        $d = $t.dir
        $exists = Test-Path $d
        $size = ""
        if ($exists) {
            $bytes = (Get-ChildItem $d -Recurse -Force -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
            $size = " (" + [math]::Round($bytes / 1MB, 1) + " MB)"
        }
        Write-Host ("  [{0}] {1}{2}  {3}" -f ($(if ($exists) { "x" } else { " " })), $t.name, $size, $(if ($exists) { $d } else { "(不存在)" }))
    }
    Write-Host ""
    $key = Read-Host "输入 RESET 并回车以删除以上全部数据, 直接回车取消"
    if ($key -ne "RESET") { Write-Host "  已取消" -ForegroundColor Yellow; return }
    foreach ($t in $targets) {
        $d = $t.dir
        if (Test-Path $d) {
            try { Remove-Item $d -Recurse -Force -ErrorAction Stop; Write-Host "  已删除: $d" -ForegroundColor Green }
            catch { Write-Host "  删除失败: $d ($_)" -ForegroundColor Red }
        }
    }
    Write-Host "  用户数据清理完成" -ForegroundColor Green
}

# ---- 提交描述：按改动文件自动生成建议，可多行补充 ----
function Get-CommitDescription([string[]]$files) {
    $summary = New-Object System.Collections.ArrayList
    $hasBot    = $false; $hasWeb    = $false
    $hasDock   = $false; $hasMcp    = $false
    $hasDocs   = $false; $hasCfg    = $false
    $hasScript = $false; $hasPlug   = $false

    foreach ($f in $files) {
        $n = $f -replace "\\", "/"
        if ($n -like "botapp/*") { $hasBot = $true }
        if ($n -like "botapp/webconsole/*" -or $n -eq "webconsole.py") { $hasWeb = $true }
        if ($n -like "Dockerfile" -or $n -like "docker-compose.yml" -or $n -like ".github/*") { $hasDock = $true }
        if ($n -like "MCP/*") { $hasMcp = $true }
        if ($n -like "docs/*") { $hasDocs = $true }
        if ($n -like "config.ini" -or $n -like "*.local.ini" -or $n -like "MCP/OB/.env" -or $n -like "MCP/OB/config.yaml") { $hasCfg = $true }
        if ($n -like "scripts/*" -or $n -like "*.ps1" -or $n -like "*.bat") { $hasScript = $true }
        if ($n -like "plugins/*") { $hasPlug = $true }
    }
    if ($hasBot)  { [void]$summary.Add("核心逻辑") }
    if ($hasWeb)  { [void]$summary.Add("网页控制台") }
    if ($hasMcp)  { [void]$summary.Add("MCP 工具") }
    if ($hasPlug) { [void]$summary.Add("插件") }
    if ($hasCfg)  { [void]$summary.Add("配置") }
    if ($hasDock) { [void]$summary.Add("Docker 部署") }
    if ($hasDocs) { [void]$summary.Add("文档") }
    if ($hasScript) { [void]$summary.Add("脚本工具") }
    $auto = if ($summary.Count -gt 0) { "涉及：" + ($summary -join "、") } else { "常规更新" }
    $auto += "；共 $($files.Count) 个文件："
    $files | ForEach-Object { $auto += "`n    - " + $_ }

    Write-Host "`n  建议描述（可修改）:" -ForegroundColor Cyan
    Write-Host ("    " + ($auto -replace "`n", "`n    ")) -ForegroundColor DarkGray
    $yn = Read-Host "`n  使用建议描述? [Y/n]"
    if ($yn -match "^(y|yes|是)?$") { return $auto }
    Write-Host "  输入描述（可多行, 单独一行 . 结束, 空回车跳过）:" -ForegroundColor Cyan
    $lines = New-Object System.Collections.ArrayList
    while ($true) {
        $line = Read-Host "  >"
        if ($line -eq ".") { break }
        if ([string]::IsNullOrWhiteSpace($line)) {
            if ($lines.Count -eq 0) { return "" }
            break
        }
        [void]$lines.Add($line)
    }
    return ($lines -join "`n")
}

# ---- 一键推送 + 触发 Docker 构建 ----
function Push-Build {
    Write-Head "一键推送 + 触发构建"

    # 1. 未提交改动
    $status = @(git status --porcelain)
    if ($status.Count -eq 0) {
        Write-Host "  工作区干净, 无改动可推送" -ForegroundColor Yellow
        $yn = Read-Host "  是否仍要触发 Docker 构建? [y/N]"
        if ($yn -notmatch "^y") { return }
        Tag-Next; return
    }

    Write-Host "`n  当前改动 ($($status.Count) 项):"
    $status | ForEach-Object { Write-Host ("    " + $_) -ForegroundColor Gray }
    $excludes = @(Get-Excludes)

    # 2. 敏感/个性文件逐个确认是否更新（默认排除）
    Write-Host "`n  以下为可配置/含密钥的文件, 请确认是否纳入本次更新:"
    $toExclude = New-Object System.Collections.ArrayList
    foreach ($f in $CandidateFiles) {
        $hasChange = $false
        foreach ($line in $status) {
            if ($line.Substring(3).Trim() -like "*$($f.Replace('/','\'))*" -or
                $line.Substring(3).Trim() -eq $f) { $hasChange = $true; break }
        }
        if (-not $hasChange) { continue }
        if ($excludes -contains $f) {
            Write-Host ("    [跳过] $f  (已在排除列表)") -ForegroundColor DarkGray
            [void]$toExclude.Add($f)
            continue
        }
        $def = "N"
        if ($f -in @("prompt.txt", "prompt_extra.txt")) { $def = "Y" }
        $ask = Read-Host ("    更新 $f ? [y/N]" + $(if ($def -eq "Y") { " (默认Y)" } else { "" }))
        if ([string]::IsNullOrWhiteSpace($ask)) { $ask = $def }
        if ($ask -match "^(y|yes|是)$") {
            Write-Host "       -> 纳入本次更新" -ForegroundColor DarkYellow
        } else {
            Write-Host "       -> 已排除并记入排除列表" -ForegroundColor Yellow
            Add-Exclude $f
            [void]$toExclude.Add($f)
        }
    }

    # 3. stage 全部, 再取消排除文件
    git add -A -- . *> $null
    foreach ($xf in $toExclude) {
        git reset -q -- $xf *> $null
    }
    if ($excludes) {
        foreach ($xf in $excludes) {
            git reset -q -- $xf *> $null
        }
    }

    $staged = @(git diff --cached --name-only)
    if ($staged.Count -eq 0) {
        Write-Host "`n  没有纳入的任何文件, 取消提交" -ForegroundColor Yellow
        return
    }
    Write-Host "`n  将提交以下文件:" -ForegroundColor Cyan
    $staged | ForEach-Object { Write-Host ("    * " + $_) -ForegroundColor Gray }

    # 4. commit（标题 + 多行描述）
    $branch = git branch --show-current
    $defaultMsg = "update: " + (Get-Date -Format "yyyy-MM-dd HH:mm")
    $msg = Read-Host "`n  提交标题 (回车用: $defaultMsg)"
    if ([string]::IsNullOrWhiteSpace($msg)) { $msg = $defaultMsg }
    $desc = Get-CommitDescription $staged
    git add -A -- . *> $null
    foreach ($xf in $toExclude) { git reset -q -- $xf *> $null }
    if ($excludes) { foreach ($xf in $excludes) { git reset -q -- $xf *> $null } }
    if ([string]::IsNullOrWhiteSpace($desc)) {
        git -c i18n.commitEncoding=utf-8 commit -m $msg *> $null
    } else {
        git -c i18n.commitEncoding=utf-8 commit -m $msg -m $desc *> $null
    }
    if ($LASTEXITCODE -ne 0) { Write-Host "  提交失败" -ForegroundColor Red; return }

    # 5. push
    Write-Host "`n  推送 $branch ..." -ForegroundColor Cyan
    git push origin $branch 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "  推送失败(检查网络/代理)" -ForegroundColor Red; return }
    Write-Host ("  已推送到 origin/" + $branch) -ForegroundColor Green

    # 6. 触发 Docker 构建
    $doTag = Read-Host "`n  触发 ghcr 镜像构建? (打 v* tag) [y/N]"
    if ($doTag -match "^(y|yes|是)$") { Tag-Next }
}

function Tag-Next {
    # 取当前最大 v* tag, 自动 +1 (v1.0.2 -> v1.0.3)
    $tags = @(git tag --list "v*")
    $maj = 1; $min = 0; $pat = 0
    foreach ($t in $tags) {
        if ($t -match "^v(\d+)\.(\d+)\.(\d+)$") {
            if ([int]$Matches[1] -gt $maj) { $maj = [int]$Matches[1]; $min = 0; $pat = 0 }
            elseif ([int]$Matches[1] -eq $maj) {
                if ([int]$Matches[2] -gt $min) { $min = [int]$Matches[2]; $pat = 0 }
                elseif ([int]$Matches[2] -eq $min -and [int]$Matches[3] -gt $pat) { $pat = [int]$Matches[3] }
            }
        }
    }
    $pat++
    $suggest = "v$maj.$min.$pat"
    $tag = Read-Host ("  打 tag 触发构建 (回车用: $suggest)")
    if ([string]::IsNullOrWhiteSpace($tag)) { $tag = $suggest }
    $tagDesc = Read-Host "  tag 描述 (回车留空)"
    if ([string]::IsNullOrWhiteSpace($tagDesc)) {
        git tag $tag 2>$null
    } else {
        git tag -a $tag -m $tagDesc 2>$null
    }
    git push origin $tag 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "  tag 推送失败" -ForegroundColor Red; return }
    Write-Host ("  已打 tag $tag 并推送, GitHub Actions 开始构建镜像~") -ForegroundColor Green
    Write-Host "  查看进度: https://github.com/Nekoluna-dot/OpenCompanion/actions" -ForegroundColor DarkCyan
}

# ---- 主菜单 ----
function Show-Menu {
    Write-Head "OpenCompanion 工具箱"
    Write-Host @"

  [1] 一键推送并触发 Docker 构建
  [2] 一键推送 (不打 tag / 不触发构建)
  [3] 清理项目缓存 (__pycache__ / *.pyc / 构建产物)
  [4] 清理用户数据 (对话 / OB记忆 / 日志 / 微信会话)
  [5] 查看 / 编辑排除列表 (.pushignore)
  [0] 退出
"@
    $c = Read-Host "  请选择"
    switch ($c) {
        "1" { Push-Build }
        "2" { git push origin (git branch --show-current) 2>$null; Write-Host "  已推送" -ForegroundColor Green }
        "3" { Clear-Cache }
        "4" { Clear-Data }
        "5" {
            Write-Head "排除列表 (.pushignore) 内容:"
            if (Test-Path $ExcludeFile) { Get-Content $ExcludeFile -Encoding UTF8 | ForEach-Object { Write-Host ("  " + $_) } }
            else { Write-Host "  (空)" }
            $hf = Read-Host "`n  输入完整路径名可移出排除列表 (回车返回)"
            if ($hf) { Remove-Exclude $hf }
        }
        "0" { Write-Host "  再见~" -ForegroundColor DarkGray; return }
        default { Write-Host "  无效输入" -ForegroundColor Red }
    }
    Show-Menu
}

switch ($Action) {
    "push"  { Push-Build }
    "cache" { Clear-Cache }
    "data"  { Clear-Data }
    default { Show-Menu }
}