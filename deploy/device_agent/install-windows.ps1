<#
.SYNOPSIS
  Cài c2a-agent trên Windows bằng MỘT lệnh — chạy ẨN, tự bật lại khi mở máy.

.DESCRIPTION
  Vì sao có script này: cách cài cũ bắt người dùng giữ một cửa sổ PowerShell
  mở suốt — "đóng là agent dừng, bot mất kết nối". Người dùng tắt nhầm cửa sổ
  là thiết bị offline mà không ai báo. Bước tự-chạy-khi-mở-máy lại là 5 bước
  bấm tay trong Task Scheduler, đủ dài để phần lớn người dùng bỏ qua.

  Script này làm trọn một lần:
    1. tải c2a_agent.py về %LOCALAPPDATA%\c2a-agent\ (thư mục riêng của user);
    2. cất token vào BIẾN MÔI TRƯỜNG USER (C2A_TOKEN) — không nằm trong dòng
       lệnh của task, nên không lộ qua cột Command line của Task Manager;
    3. tạo Scheduled Task chạy pythonw.exe — KHÔNG cửa sổ, không có gì để tắt
       nhầm; trigger lúc đăng nhập; tự khởi động lại mỗi phút nếu agent chết;
    4. chạy task ngay và kiểm tra tiến trình còn sống.

  Chạy lại script = cập nhật (tải agent mới, ghi đè task cũ). -Uninstall để gỡ
  sạch (task + thư mục + biến môi trường).

.EXAMPLE
  # Cài (dán MỘT khối — PowerShell thường, không cần admin):
  irm https://raw.githubusercontent.com/TriTue2011/chatgpt2api/main/deploy/device_agent/install-windows.ps1 -OutFile "$env:TEMP\c2a-install.ps1"
  & "$env:TEMP\c2a-install.ps1" -Url wss://gpt.vhtatn.io.vn/api/devices/agent -Token "tok_..." -Paths "D:\","E:\" -AllowWrite -AllowExec -AllowPower

.EXAMPLE
  & "$env:TEMP\c2a-install.ps1" -Uninstall
#>
[CmdletBinding()]
param(
  [string]$Url = "",
  [string]$Token = "",
  [string[]]$Paths = @(),
  [switch]$AllowWrite,
  [switch]$AllowExec,
  [switch]$AllowPower,
  [string]$Label = "",
  # Nguồn tải agent — đổi được để test nhánh khác / mirror nội bộ.
  [string]$AgentSource = "https://raw.githubusercontent.com/TriTue2011/chatgpt2api/main/deploy/device_agent/c2a_agent.py",
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "c2a-agent"
$Dir = Join-Path $env:LOCALAPPDATA "c2a-agent"
$AgentPy = Join-Path $Dir "c2a_agent.py"
$LogFile = Join-Path $Dir "c2a-agent.log"

function Say([string]$msg) { Write-Host "[c2a-install] $msg" }

# ── Gỡ ───────────────────────────────────────────────────────────────────────
if ($Uninstall) {
  try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Say "đã xoá task '$TaskName'"
  } catch {}
  Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "c2a_agent\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir; Say "đã xoá $Dir" }
  [Environment]::SetEnvironmentVariable("C2A_TOKEN", $null, "User")
  Say "đã xoá biến môi trường C2A_TOKEN. Gỡ xong."
  return
}

# ── Kiểm tra đầu vào ─────────────────────────────────────────────────────────
if (-not $Url)   { throw "thiếu -Url (vd wss://gpt.vhtatn.io.vn/api/devices/agent)" }
if (-not $Token) { throw "thiếu -Token (tạo ở web UI: MCP -> Thiết bị của tôi)" }
if (-not $Paths -or $Paths.Count -eq 0) { throw "thiếu -Paths (vd -Paths `"D:\`",`"E:\`")" }

# pythonw = python không console. Đây là cốt lõi của "chạy ẩn": không có cửa
# sổ nào sinh ra thì không có gì để tắt nhầm.
$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) {
  $py = (Get-Command python -ErrorAction SilentlyContinue).Source
  if ($py) { $cand = Join-Path (Split-Path $py) "pythonw.exe"; if (Test-Path $cand) { $pyw = $cand } }
}
if (-not $pyw) {
  throw "không tìm thấy pythonw.exe — cài Python trước:  winget install Python.Python.3.12  (xong ĐÓNG rồi MỞ LẠI PowerShell)"
}
Say "pythonw: $pyw"

# ── Tải agent ────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Invoke-RestMethod $AgentSource -OutFile $AgentPy
Say "đã tải agent -> $AgentPy"

# ── Token vào biến môi trường USER ──────────────────────────────────────────
# KHÔNG nhét token vào arguments của task: cột Command line trong Task
# Manager/`wmic process` ai cùng máy cũng đọc được. Biến môi trường User thì
# chỉ tiến trình của chính user này thấy.
[Environment]::SetEnvironmentVariable("C2A_TOKEN", $Token, "User")
Say "đã cất token vào biến môi trường C2A_TOKEN (User)"

# ── Dựng task ────────────────────────────────────────────────────────────────
$flags = @()
if ($AllowWrite) { $flags += "--allow-write" }
if ($AllowExec)  { $flags += "--allow-exec" }
if ($AllowPower) { $flags += "--allow-power" }
$pathArgs = ($Paths | ForEach-Object { "--path `"$_`"" }) -join " "
$labelArg = if ($Label) { "--label `"$Label`"" } else { "" }
# Log ra file — chạy ẩn thì đây là chỗ duy nhất xem agent đang làm gì.
$argLine = "`"$AgentPy`" --url $Url $pathArgs $labelArg $($flags -join ' ') --log-file `"$LogFile`""

$action  = New-ScheduledTaskAction -Execute $pyw -Argument $argLine -WorkingDirectory $Dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
  -MultipleInstances IgnoreNew -Hidden
# Chạy dưới chính user hiện tại, chỉ khi đã đăng nhập (Interactive) — agent
# cần HKCU + biến môi trường User; "run whether logged on or not" đòi cất mật
# khẩu Windows, không đáng cho một agent mức user.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal | Out-Null
Say "đã tạo task '$TaskName' (ẩn, tự chạy khi đăng nhập, tự hồi khi chết)"

# ── Chạy ngay + xác minh ─────────────────────────────────────────────────────
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 4
$proc = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match "c2a_agent\.py" }
if ($proc) {
  Say "agent ĐANG CHẠY ẨN (PID $($proc.ProcessId | Select-Object -First 1))."
  Say "log: Get-Content `"$LogFile`" -Tail 20 -Wait"
  Say "kiểm tra: nhắn bot 'kiểm tra danh sách thiết bị của tôi' — phải thấy 🟢 online."
} else {
  Say "CHƯA thấy tiến trình agent. Xem lỗi ở log:"
  Say "  Get-Content `"$LogFile`" -Tail 40"
  if (Test-Path $LogFile) { Get-Content $LogFile -Tail 15 }
}
Say "gỡ cài đặt:  & `"$PSCommandPath`" -Uninstall"
