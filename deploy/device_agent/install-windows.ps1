<#
.SYNOPSIS
  Cai c2a-agent tren Windows bang MOT lenh - chay AN, tu bat lai khi mo may.

.DESCRIPTION
  Vi sao co script nay: cach cai cu bat nguoi dung giu mot cua so PowerShell
  mo suot - "dong la agent dung, bot mat ket noi". Nguoi dung tat nham cua so
  la thiet bi offline ma khong ai bao. Buoc tu-chay-khi-mo-may lai la 5 buoc
  bam tay trong Task Scheduler, du dai de phan lon nguoi dung bo qua.

  QUAN TRONG - file nay CO Y viet KHONG DAU: PowerShell 5.1 doc file .ps1
  khong BOM theo ANSI, tieng Viet UTF-8 vo thanh ky tu rac va PHA CU PHAP
  (da xay ra that: dau nhay trong chuoi throw vo, script khong parse duoc
  tren may nguoi dung). ASCII thuan thi moi PowerShell deu doc dung.

  Script lam tron mot lan:
    1. tai c2a_agent.py ve %LOCALAPPDATA%\c2a-agent\ (thu muc rieng cua user);
    2. cat token vao BIEN MOI TRUONG USER (C2A_TOKEN) - khong nam trong dong
       lenh cua task, nen khong lo qua cot Command line cua Task Manager;
    3. tao Scheduled Task chay pythonw.exe - KHONG cua so, khong co gi de tat
       nham; chay luc dang nhap; tu khoi dong lai moi phut neu agent chet;
    4. chay task ngay va kiem tra tien trinh con song.

  Chay lai script = cap nhat (tai agent moi, ghi de task cu). -Uninstall de go
  sach (task + thu muc + bien moi truong).

.EXAMPLE
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
  # Nguon tai agent - doi duoc de test nhanh khac / mirror noi bo.
  [string]$AgentSource = "https://raw.githubusercontent.com/TriTue2011/chatgpt2api/main/deploy/device_agent/c2a_agent.py",
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "c2a-agent"
$Dir = Join-Path $env:LOCALAPPDATA "c2a-agent"
$AgentPy = Join-Path $Dir "c2a_agent.py"
$LogFile = Join-Path $Dir "c2a-agent.log"

function Say([string]$msg) { Write-Host "[c2a-install] $msg" }

# --- Go cai dat -------------------------------------------------------------
if ($Uninstall) {
  try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Say "da xoa task '$TaskName'"
  } catch {}
  Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "c2a_agent\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir; Say "da xoa $Dir" }
  [Environment]::SetEnvironmentVariable("C2A_TOKEN", $null, "User")
  Say "da xoa bien moi truong C2A_TOKEN. Go xong."
  return
}

# --- Kiem tra dau vao ---------------------------------------------------------
if (-not $Url)   { throw "thieu -Url (vd wss://gpt.vhtatn.io.vn/api/devices/agent)" }
if (-not $Token) { throw "thieu -Token (tao o web UI: MCP -> Thiet bi cua toi)" }
if (-not $Paths -or $Paths.Count -eq 0) { throw "thieu -Paths (vd -Paths 'D:\','E:\')" }

# pythonw = python khong console. Day la cot loi cua "chay an": khong co cua
# so nao sinh ra thi khong co gi de tat nham.
$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) {
  $py = (Get-Command python -ErrorAction SilentlyContinue).Source
  if ($py) { $cand = Join-Path (Split-Path $py) "pythonw.exe"; if (Test-Path $cand) { $pyw = $cand } }
}
if (-not $pyw) {
  throw "khong tim thay pythonw.exe - cai Python truoc:  winget install Python.Python.3.12  (xong DONG roi MO LAI PowerShell)"
}
Say "pythonw: $pyw"

# --- Tai agent ----------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
if (Test-Path $AgentSource) {
  Copy-Item $AgentSource $AgentPy -Force
} else {
  Invoke-RestMethod $AgentSource -OutFile $AgentPy
}
Say "da tai agent -> $AgentPy"

# --- Token vao bien moi truong USER -------------------------------------------
# KHONG nhet token vao arguments cua task: cot Command line trong Task
# Manager / wmic process ai cung may cung doc duoc. Bien moi truong User thi
# chi tien trinh cua chinh user nay thay.
[Environment]::SetEnvironmentVariable("C2A_TOKEN", $Token, "User")
Say "da cat token vao bien moi truong C2A_TOKEN (User)"

# --- Dung task ------------------------------------------------------------------
$flags = @()
if ($AllowWrite) { $flags += "--allow-write" }
if ($AllowExec)  { $flags += "--allow-exec" }
if ($AllowPower) { $flags += "--allow-power" }
# NHAN DOI backslash cuoi truoc dau nhay dong. Quy tac dong lenh Windows
# (MSVCRT): `\"` la ESCAPE dau nhay, nen '--path "D:\"' bi doc thanh mot
# chuoi rac 'D:" --path E:"' dinh chum tat ca path phia sau. Do that 30/07
# (case-win, -Paths "D:\","E:\"): agent tu choi moi lenh voi loi
#   ngoai pham vi cho phep cua thiet bi nay (D:\" --path E:")
# '"D:\\"' thi doc dung thanh 'D:\'. Chi path ket thuc bang backslash (goc o
# dia) dinh loi nay — 'D:\Data' khong sao, nen truoc gio khong ai thay.
$pathArgs = ($Paths | ForEach-Object {
  $p = $_ -replace '(\\+)$', '$1$1'
  '--path "' + $p + '"'
}) -join " "
$labelArg = ""
if ($Label) { $labelArg = '--label "' + $Label + '"' }
# Log ra file - chay an thi day la cho duy nhat xem agent dang lam gi.
$argLine = '"' + $AgentPy + '" --url ' + $Url + ' ' + $pathArgs + ' ' + $labelArg + ' ' + ($flags -join ' ') + ' --log-file "' + $LogFile + '"'

$action  = New-ScheduledTaskAction -Execute $pyw -Argument $argLine -WorkingDirectory $Dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
  -MultipleInstances IgnoreNew -Hidden
# Chay duoi chinh user hien tai, chi khi da dang nhap (Interactive) - agent
# can HKCU + bien moi truong User; "run whether logged on or not" doi cat mat
# khau Windows, khong dang cho mot agent muc user.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal | Out-Null
Say "da tao task '$TaskName' (an, tu chay khi dang nhap, tu hoi khi chet)"

# --- Chay ngay + xac minh -------------------------------------------------------
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 4
$proc = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match "c2a_agent\.py" }
if ($proc) {
  $pid1 = ($proc | Select-Object -First 1).ProcessId
  Say "agent DANG CHAY AN (PID $pid1)."
  Say "log:  Get-Content '$LogFile' -Tail 20 -Wait"
  Say "kiem tra: nhan bot 'kiem tra danh sach thiet bi cua toi' - phai thay online."
} else {
  Say "CHUA thay tien trinh agent. Xem loi o log:"
  Say "  Get-Content '$LogFile' -Tail 40"
  if (Test-Path $LogFile) { Get-Content $LogFile -Tail 15 }
}
Say "go cai dat:  & '$PSCommandPath' -Uninstall"
