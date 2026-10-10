# ============================================================================
#  玉用去水印 —— 一键构建脚本（PyInstaller 打包 + Inno Setup 生成安装包）
#  用法：  pwsh -File build.ps1
#  可选：  -SkipPyInstaller   只重新生成安装包
#          -SkipInstaller     只重新打包 exe
# ============================================================================
[CmdletBinding()]
param(
    [switch]$SkipPyInstaller,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$AppDir = Join-Path $Root "app"

$Python = if ($env:YUWATER_PYTHON) { $env:YUWATER_PYTHON }
          else { "C:\Users\26235\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" }
$Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "!! $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Python)) { Fail "找不到 Python: $Python`n可用环境变量 YUWATER_PYTHON 指定。" }

# ---------------------------------------------------------------- 1. 算法自测
Step "1/5 算法回环自测（合成水印注入 → 去除 → 逐像素比对）"
Push-Location $AppDir
& $Python "selftest.py"
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "自测失败，先修算法再打包。" }
Pop-Location

# ---------------------------------------------------------------- 2. 图标
Step "2/5 生成图标资源"
if (Test-Path (Join-Path $AppDir "make_icon.py")) {
    & $Python (Join-Path $AppDir "make_icon.py")
} else {
    Write-Host "（跳过：没有 make_icon.py）" -ForegroundColor Yellow
}
$icon = Join-Path $AppDir "assets\app.ico"
if (-not (Test-Path $icon)) { Fail "缺少图标：$icon" }

# ---------------------------------------------------------------- 3. 打包 exe
if (-not $SkipPyInstaller) {
    Step "3/5 PyInstaller 打包"
    Push-Location $AppDir
    if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
    if (Test-Path "dist")  { Remove-Item "dist"  -Recurse -Force }
    & $Python -m PyInstaller --clean --noconfirm "build.spec"
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "PyInstaller 失败。" }
} else {
    Step "3/5 跳过 PyInstaller（-SkipPyInstaller）"
}

$exe = Join-Path $AppDir "dist\玉用去水印\玉用去水印.exe"
if (-not (Test-Path $exe)) { Fail "没有找到可执行文件：$exe" }
$exeSize = (Get-Item $exe).Length
$dirSize = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("可执行文件: {0:N1} MB / 目录合计: {1:N1} MB" -f ($exeSize/1MB), ($dirSize/1MB))

# ---------------------------------------------------------------- 4. 安装包
if (-not $SkipInstaller) {
    Step "4/5 Inno Setup 生成安装包"
    if (-not (Test-Path $Iscc)) { Fail "找不到 Inno Setup: $Iscc" }
    Copy-Item (Join-Path $Root "README.txt") (Join-Path $AppDir "dist\玉用去水印\README.txt") -Force
    & $Iscc (Join-Path $Root "installer.iss")
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup 编译失败。" }
} else {
    Step "4/5 跳过 Inno Setup（-SkipInstaller）"
}

# ---------------------------------------------------------------- 5. 汇总
Step "5/5 构建产物"
Get-ChildItem (Join-Path $Root "dist") -File -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length/1MB)) }
Get-ChildItem $AppDir -Filter "dist" -Directory -ErrorAction SilentlyContinue | Out-Null
Write-Host "`n完成 ✅" -ForegroundColor Green
