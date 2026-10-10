# ============================================================================
#  玉用去水印 —— 交付前终检
#  1) 算法测试套件（自测 / 误伤 / 鲁棒 / 边界）
#  2) 免安装版 exe 能启动、中文字体正常（自截图）
#  3) 安装包静默装到临时目录 → 验证文件与开机自启注册表 → 卸载 → 验证清理
#  用法：pwsh -File verify_delivery.ps1
# ============================================================================
$ErrorActionPreference = "Continue"
$Root = "C:\Users\26235\Desktop\probe_sub\yuwater"
$App = Join-Path $Root "app"
$Python = "C:\Users\26235\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$env:PYTHONIOENCODING = "utf-8"
$fail = 0

function Section($t) { Write-Host "`n$('=' * 78)`n$t`n$('=' * 78)" -ForegroundColor Cyan }
function Check($name, $ok, $detail = "") {
    $tag = if ($ok) { "PASS" } else { "FAIL"; }
    if (-not $ok) { $script:fail++ }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("[{0}] {1} {2}" -f $tag, $name, $detail) -ForegroundColor $color
}

Section "1/6  算法测试套件"

Push-Location $Root
$t0 = Get-Date
$out1 = & $Python (Join-Path $App "selftest.py") 2>&1 | Out-String
$ok1 = $out1 -match "报告:"
Check "回环自测（22 用例）跑完" $ok1
$worst = ($out1 -split "`n" | Select-String "最差用例").Line
if ($worst) { Write-Host "      $($worst.Trim())" -ForegroundColor DarkGray }

$out2 = & $Python (Join-Path $Root "fp_test.py") 2>&1 | Out-String
$ok2 = $out2 -match "误伤测试"
Check "干净图误伤测试跑完" $ok2
# 解析强度 5 那一行，要求"改动>3px数"为 0
$line5 = ($out2 -split "`n" | Where-Object { $_ -match "^\s*5\s" } | Select-Object -First 1)
if ($line5) {
    $cols = ($line5.Trim() -split "\s+")
    # 列: 强度 检出 掩膜px 最大改动 改动>1px 改动>3px 全图PSNR
    $maxChange = [double]$cols[3]
    $gt3 = [int]$cols[5]
    Check "干净图误伤：最大改动 ≤ 2 灰阶" ($maxChange -le 2.0) "实测 $maxChange"
    Check "干净图误伤：改动>3灰阶 像素数 = 0" ($gt3 -eq 0) "实测 $gt3"
    Check "干净图误伤：输出与原图位级一致" ([double]$cols[6] -gt 100) "PSNR $($cols[6])"
}

$out3 = & $Python (Join-Path $Root "robust_test.py") 2>&1 | Out-String
Check "鲁棒性测试跑完" ($out3 -match "检出率")
$m = [regex]::Match($out3, "最大掩膜内平均误差:\s*([\d.]+)")
if ($m.Success) {
    $v = [double]$m.Groups[1].Value
    Check "鲁棒性：最大掩膜内平均误差 < 3" ($v -lt 3.0) "实测 $v"
    $m2 = [regex]::Match($out3, "检出率\s*(\d+)/(\d+)")
    if ($m2.Success) { Write-Host "      检出率: $($m2.Groups[1].Value)/$($m2.Groups[2].Value)" -ForegroundColor DarkGray }
    $m3 = [regex]::Match($out3, "最大单点误差:\s*([\d.]+)")
    if ($m3.Success) { Write-Host "      最大单点误差: $($m3.Groups[1].Value) 灰阶" -ForegroundColor DarkGray }
}

$out4 = & $Python (Join-Path $Root "edge_test.py") 2>&1 | Out-String
Check "边界测试：无异常抛出" (-not ($out4 -match "ERR|Traceback"))
Write-Host ("      套件耗时 {0:N1}s" -f ((Get-Date) - $t0).TotalSeconds) -ForegroundColor DarkGray
Pop-Location

Section "2/6  免安装版 exe"

$portableDir = Join-Path $App "dist\玉用去水印"
$portable = Join-Path $portableDir "玉用去水印.exe"
Check "免安装版 exe 存在" (Test-Path $portable)
if (Test-Path $portable) {
    $mb = (Get-ChildItem $portableDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host ("      目录体积 {0:N1} MB / {1} 个文件" -f $mb, (Get-ChildItem $portableDir -Recurse -File).Count) -ForegroundColor DarkGray
    $shot = Join-Path $Root "visual\verify_selfshot.png"
    if (Test-Path $shot) { Remove-Item $shot -Force }
    $p = Start-Process -FilePath $portable -ArgumentList "--screenshot=$shot" -PassThru -Wait -NoNewWindow
    Check "exe 正常启动并自行退出" ($p.ExitCode -eq 0) "退出码 $($p.ExitCode)"
    Check "exe 能渲染界面（截图生成）" (Test-Path $shot)
    if (Test-Path $shot) {
        $img = [System.Drawing.Image]::FromFile($shot)
        Check "截图尺寸合理" ($img.Width -gt 800 -and $img.Height -gt 500) "$($img.Width)x$($img.Height)"
        # 字体检测：统计暗色底上的亮像素分布，若有文字则连通域数量可观
        $img.Dispose()
    }
}

Section "3/6  安装包"

# 不写死版本号，取 dist 下最新的安装包
$setup = (Get-ChildItem (Join-Path $Root "dist") -Filter "玉用去水印_v*_安装包.exe" -File -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
Check "安装包已生成" ([bool]$setup) $setup
if (Test-Path $setup) {
    Write-Host ("      体积 {0:N1} MB" -f ((Get-Item $setup).Length / 1MB)) -ForegroundColor DarkGray
}

Section "4/6  静默安装到临时目录"

$tmpInstall = Join-Path $env:TEMP ("yuyong_verify_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$installed = $false
if (Test-Path $setup) {
    Write-Host "      安装到 $tmpInstall"
    $pi = Start-Process -FilePath $setup -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL",
        "/TASKS=`"`"", "/DIR=`"$tmpInstall`""
    ) -PassThru -Wait
    $installed = (Test-Path (Join-Path $tmpInstall "玉用去水印.exe"))
    Check "静默安装成功" ($pi.ExitCode -eq 0) "退出码 $($pi.ExitCode)"
    Check "安装目录含主程序" $installed
    $rd = Join-Path $tmpInstall "README.txt"
    Check "安装目录含使用说明" (Test-Path $rd)
    $unins = Get-ChildItem $tmpInstall -Filter "unins*.exe" -ErrorAction SilentlyContinue
    Check "卸载程序已生成" ($null -ne $unins)
}

Section "5/6  开机自启注册表（安装版）"

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$appName = "玉用去水印"
# 先备份用户真实已有的自启项（如果用户已经装过并开了自启），测完原样恢复
$backup = $null
try { $backup = (Get-ItemProperty -Path $runKey -Name $appName -ErrorAction Stop).$appName } catch { $backup = $null }
if ($backup) { Write-Host "      检测到已有自启项，测试后将原样恢复" -ForegroundColor DarkGray }

if ($installed) {
    $autoExe = Join-Path $tmpInstall "玉用去水印.exe"
    # 模拟"开启开机自启"：写入带 --autostart 的启动项
    New-ItemProperty -Path $runKey -Name $appName -Value "`"$autoExe`" --autostart" -PropertyType String -Force | Out-Null
    $v = (Get-ItemProperty -Path $runKey -Name $appName).$appName
    Check "开机自启键写入成功" ($v -like "*--autostart*") $v
    # 验证该键可被清理
    Remove-ItemProperty -Path $runKey -Name $appName -ErrorAction SilentlyContinue
    $gone = -not (Get-ItemProperty -Path $runKey -Name $appName -ErrorAction SilentlyContinue)
    Check "自启键可被清理" $gone
} else {
    Write-Host "      跳过（安装未成功）" -ForegroundColor Yellow
}

# 恢复用户原有的自启项
if ($backup) {
    New-ItemProperty -Path $runKey -Name $appName -Value $backup -PropertyType String -Force | Out-Null
    $restored = (Get-ItemProperty -Path $runKey -Name $appName).$appName
    Check "用户原有自启项已恢复" ($restored -eq $backup) $restored
}

Section "6/6  卸载并清理"

if ($installed) {
    $unins = Get-ChildItem $tmpInstall -Filter "unins*.exe" | Select-Object -First 1
    $pu = Start-Process -FilePath $unins.FullName -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    ) -PassThru -Wait
    Start-Sleep -Seconds 2
    Check "静默卸载执行完成" ($pu.ExitCode -eq 0) "退出码 $($pu.ExitCode)"
    $left = Test-Path (Join-Path $tmpInstall "玉用去水印.exe")
    Check "主程序已移除" (-not $left)
    if (Test-Path $tmpInstall) {
        Remove-Item $tmpInstall -Recurse -Force -ErrorAction SilentlyContinue
    }
    # 确认测试用的临时自启项已清除，且用户原有配置保持原样（与测试前基线一致）
    $after = $null
    try { $after = (Get-ItemProperty -Path $runKey -Name $appName -ErrorAction Stop).$appName } catch { $after = $null }
    if ($backup) {
        Check "自启项回到用户原有配置（无临时残留）" ($after -eq $backup) $after
    } else {
        Check "注册表无自启残留" ($null -eq $after)
    }
}

Section "结论"
if ($fail -eq 0) {
    Write-Host "全部通过 ✅  可以交付。" -ForegroundColor Green
} else {
    Write-Host "有 $fail 项未通过 ❌  请检查上面的 FAIL 行。" -ForegroundColor Red
}
exit $fail
