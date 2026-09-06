# 把這個專案同步到 H:\OS\Github\chanLik1208-dev\roblox-ui-preview\
#
# 為什麼需要這支:H 上那份本來是手工拖過去的,結果兩邊已經在漂 ——
# H 版混了 10 個「在 H 上重新編譯出來」的 .pyc(每個剛好比 C 版大 17 bytes,
# 正好是路徑長度差),而且其中 layout.cpython-310.pyc 是編譯自舊版原始碼的 stale 檔。
# 原始碼一致但快取不一致,這種漂移沒人會發現。
#
#   powershell -ExecutionPolicy Bypass -File sync_to_h.ps1
#   powershell -ExecutionPolicy Bypass -File sync_to_h.ps1 -WhatIf   # 只看會做什麼

param(
    [string]$Destination = 'H:\OS\Github\chanLik1208-dev\roblox-ui-preview',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$Source = $PSScriptRoot

if (-not (Test-Path (Split-Path $Destination -Parent))) {
    Write-Error "目的地的上層目錄不存在:$(Split-Path $Destination -Parent)（H: 掛載了嗎？）"
}

# 跟 .gitignore 對齊。out/ 是產出的 PNG，__pycache__ 是本機快取，
# _fixture.rbxmx 每次跑測試會重新產生 —— 三種都不該跨機器搬。
$excludeDirs  = @('out', '__pycache__', '.git', '.venv')
$excludeFiles = @('*.pyc', '_fixture.rbxmx')

# /XD 與 /XF 排除掉的東西，/MIR 是不會去刪的（robocopy 根本不看它們）。
# 所以目的地既有的 __pycache__ / out / *.pyc / _fixture.rbxmx 要自己清 ——
# 那正是目前 H 上殘留 stale .pyc 與舊 fixture 的原因。
if (Test-Path $Destination) {
    foreach ($d in @('__pycache__', 'out')) {
        Get-ChildItem $Destination -Recurse -Directory -Filter $d -ErrorAction SilentlyContinue |
            ForEach-Object {
                Write-Host "  清掉殘留目錄 $($_.FullName)"
                if (-not $WhatIf) { Remove-Item $_.FullName -Recurse -Force }
            }
    }
    foreach ($f in $excludeFiles) {
        Get-ChildItem $Destination -Recurse -File -Filter $f -ErrorAction SilentlyContinue |
            ForEach-Object {
                Write-Host "  清掉殘留檔案 $($_.FullName)"
                if (-not $WhatIf) { Remove-Item $_.FullName -Force }
            }
    }
}

$roboArgs = @(
    $Source, $Destination,
    '/MIR',                       # 鏡像：目的地多出來的東西會被刪掉（這正是要的）
    '/XD') + $excludeDirs + @('/XF') + $excludeFiles + @(
    '/NFL', '/NDL', '/NJH', '/NP', '/R:1', '/W:1'
)
if ($WhatIf) { $roboArgs += '/L' }

Write-Host "同步 $Source"
Write-Host "  -> $Destination"
if ($WhatIf) { Write-Host '  (WhatIf：只列出不實做)' }

& robocopy.exe @roboArgs | Out-Host

# robocopy 的 exit code：0-7 是成功（8 以上才是真的失敗）
$code = $LASTEXITCODE
if ($code -ge 8) {
    Write-Error "robocopy 失敗，exit code $code"
}

if (-not $WhatIf) {
    $srcCount = (Get-ChildItem $Source -Recurse -File |
        Where-Object { $_.FullName -notmatch '\\(out|__pycache__|\.git|\.venv)\\' -and
                       $_.Extension -ne '.pyc' -and $_.Name -ne '_fixture.rbxmx' }).Count
    $dstCount = (Get-ChildItem $Destination -Recurse -File).Count
    Write-Host ''
    Write-Host "來源 $srcCount 個檔 / 目的地 $dstCount 個檔"
    if ($srcCount -ne $dstCount) {
        Write-Warning '兩邊檔案數不一樣 —— 目的地可能有殘留的東西沒被 /MIR 清掉。'
    } else {
        Write-Host '同步完成。' -ForegroundColor Green
    }
}
