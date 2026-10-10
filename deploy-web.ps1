<#
  一键部署网页版到 GitHub。

  用法：
    1) 先设置 Token（GitHub → Settings → Developer settings →
       Personal access tokens → Fine-grained tokens，
       只勾这一个仓库的 Contents: Read and write）
         $env:GITHUB_TOKEN = "github_pat_xxxxxxxx"
    2) 运行：
         pwsh -File deploy-web.ps1

  说明：GitHub 早已不允许用账号密码推送，必须用 Token。
        脚本不会保存 Token，只在本次会话的环境变量里用。
#>
[CmdletBinding()]
param(
  [string]$Repo = "ikun1987/demo",
  [string]$Branch = "main",
  [string]$Message = "添加「玉用去水印」网页版：豆包水印清除（移动端优先，纯浏览器本地处理）",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Info($m) { Write-Host "  $m" }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [X] $m" -ForegroundColor Red; exit 1 }

Write-Host "`n===== 部署网页版到 $Repo =====`n" -ForegroundColor Cyan

# --- 1. 构建 ---
Write-Host "[1/5] 构建网页版（base=/<repo>/）"
Push-Location "$root\web"
$env:BASE = "/" + ($Repo.Split('/')[-1]) + "/"
try {
  & npm run build 2>&1 | Select-Object -Last 6 | ForEach-Object { Info $_ }
  if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "构建失败" }
} finally { Pop-Location }
if (-not (Test-Path "$root\web\dist\index.html")) { Fail "没找到构建产物 web\dist\index.html" }
$size = (Get-ChildItem "$root\web\dist" -Recurse -File | Measure-Object Length -Sum).Sum
Ok ("构建完成，产物 {0:N1} MB" -f ($size / 1MB))
if ($size -gt 95MB) { Warn "产物超过 95MB，GitHub 单次推送可能被拒" }

# --- 2. 初始化仓库 ---
Write-Host "`n[2/5] 准备仓库"
if (-not (Test-Path "$root\.git")) {
  & git init -q
  & git branch -M $Branch
  Ok "已初始化 git 仓库"
} else { Ok "已是 git 仓库" }

# --- 3. Token 组装推送地址 ---
Write-Host "`n[3/5] 校验凭据"
$token = $env:GITHUB_TOKEN
if (-not $token) {
  Warn "没有设置 GITHUB_TOKEN"
  Write-Host @"

  请按下面两步操作（GitHub 不接受账号密码推送，必须用 Token）：

    1) 打开 https://github.com/settings/personal-access-tokens/new
       · Repository access  选 Only select repositories → 勾 $Repo
       · Permissions → Repository permissions → Contents 设为 Read and write
       · 生成后复制那串 github_pat_...  （只显示一次，务必先存好）

    2) 在本窗口执行：
         `$env:GITHUB_TOKEN = "粘贴你的token"
         pwsh -File deploy-web.ps1

"@ -ForegroundColor Yellow
  exit 2
}

$remote = "https://x-access-token:$token@github.com/$Repo.git"

# --- 4. 提交 ---
Write-Host "`n[4/5] 提交改动"
& git add -A
$staged = (& git diff --cached --name-only) -join "`n"
if (-not $staged) { Warn "没有需要提交的改动" }
else {
  $count = ($staged -split "`n").Count
  Info "暂存 $count 个文件"
  & git -c user.name="yuyong-deploy" -c user.email="deploy@local" commit -q -m $Message
  Ok "已提交"
}

if ($DryRun) { Warn "-DryRun：到此为止，未推送"; exit 0 }

# --- 5. 推送 ---
Write-Host "`n[5/5] 推送"
& git remote remove origin 2>$null | Out-Null
& git remote add origin $remote
$push = & git push -u origin $Branch 2>&1
$push | Select-Object -Last 8 | ForEach-Object { Info $_ }
if ($LASTEXITCODE -ne 0) {
  & git remote set-url origin "https://github.com/$Repo.git"
  Fail "推送失败（检查 Token 权限是否含 Contents: Read and write）"
}
& git remote set-url origin "https://github.com/$Repo.git"

Ok "推送成功"
Write-Host @"

===== 完成 =====

  · 仓库：https://github.com/$Repo
  · 若已开启 GitHub Pages（Settings → Pages → Source 选 GitHub Actions），
    几分钟后网页版可访问：
        https://$($Repo.Split('/')[0]).github.io/$($Repo.Split('/')[-1])/
  · 首次需要在 Settings → Pages 里把 Source 设为「GitHub Actions」。
  · 手机浏览器打开上面的地址即可使用；建议「添加到主屏幕」当 App 用。

"@ -ForegroundColor Cyan
