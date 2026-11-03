<#
.SYNOPSIS
    诊断并修复 Windows 目录权限，解决 DSH / 沙箱在某个目录"启动即失败"的问题。

.DESCRIPTION
    症状：在某个目录跑命令时报 SetNamedSecurityInfoW failed (Win32 5)，
    或沙箱无法为工作目录建立授权。根因通常是目录缺少 WRITE_OWNER 权限。

    默认只诊断，不改任何东西；加 -Fix 才会给当前用户补一条完全控制权限。
    改动前会把原始 SDDL 打印出来，方便回滚。

.PARAMETER Path
    要检查的目录。

.PARAMETER Fix
    真的去改权限。不加这个开关只诊断。

.EXAMPLE
    .\acl_fix.ps1 -Path "D:\work\myproject"

.EXAMPLE
    .\acl_fix.ps1 -Path "D:\work\myproject" -Fix
#>
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [switch]$Fix
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Error "目录不存在: $Path"
    exit 2
}
$target = (Resolve-Path -LiteralPath $Path).Path
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name

Write-Host "目录: $target"
Write-Host "当前用户: $me"
Write-Host ""

$acl = Get-Acl -LiteralPath $target
Write-Host "所有者: $($acl.Owner)"
Write-Host "原始 SDDL（回滚用，先存好）:"
Write-Host "  $($acl.Sddl)"
Write-Host ""

# 只看显式授予当前用户的规则
$mine = @($acl.Access | Where-Object {
    $_.IdentityReference.Value -eq $me -and -not $_.IsInherited
})

if ($mine.Count -gt 0) {
    Write-Host "已存在当前用户的显式权限:"
    $mine | ForEach-Object {
        Write-Host ("  {0,-12} {1}" -f $_.AccessControlType, $_.FileSystemRights)
    }
} else {
    Write-Host "没有发现当前用户的显式权限（可能只有继承权限）——这就是沙箱起不来的常见原因"
}

Write-Host ""
if (-not $Fix) {
    Write-Host "当前为【只诊断】模式，没有改动任何权限。"
    Write-Host "确认要修复时，加 -Fix 再跑一次："
    Write-Host "  .\acl_fix.ps1 -Path `"$target`" -Fix"
    exit 0
}

# ---- 修复：给当前用户在当前目录加完全控制（不递归，避免波及子项）----
Write-Host "正在为当前用户授予完全控制（仅本目录，不递归）..."
try {
    & icacls "$target" /grant "${me}:(OI)(CI)F" /T:$false 2>&1 | ForEach-Object { Write-Host "  $_" }
    $code = $LASTEXITCODE
} catch {
    Write-Host "  icacls 执行失败: $($_.Exception.Message)"
    $code = 1
}

if ($code -ne 0 -and $code -ne $null -and $code -notin 0) {
    Write-Host ""
    Write-Host "授予失败（退出码 $code）。可能原因："
    Write-Host "  1) 目录属于其它用户或系统保护目录"
    Write-Host "  2) 组策略禁止修改 ACL"
    Write-Host "  3) 需要管理员权限"
    exit 3
}

# ---- 复核 ----
$after = Get-Acl -LiteralPath $target
$check = @($after.Access | Where-Object {
    $_.IdentityReference.Value -eq $me -and -not $_.IsInherited
})
Write-Host ""
Write-Host "复核：当前用户的显式规则 $($check.Count) 条"
$check | ForEach-Object { Write-Host ("  {0,-12} {1}" -f $_.AccessControlType, $_.FileSystemRights) }

Write-Host ""
Write-Host "回滚命令（把权限恢复到原来的样子）："
Write-Host "  icacls `"$target`" /remove:g `"$me`""
Write-Host "如果原来就是这条 ACL，按上面打印的原始 SDDL 用 Set-Acl 恢复。"