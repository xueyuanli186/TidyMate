# TidyMate - clean-VM acceptance script (stage 9)
#
# Run inside the Windows 11 VM, in an elevated PowerShell:
#
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\verify-install.ps1 -Msi "C:\path\TidyMate-0.1.0-windows.msi"
#
# It installs, checks the observable contract, uninstalls, and writes a JSON report to
# %TEMP%\tidymate-vm-verify.json. It never deletes user data and never runs silently
# beyond the documented msiexec calls.

param(
    [Parameter(Mandatory = $true)][string]$Msi,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$installPath = "C:\Program Files\TidyMate"
$menuPath = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\TidyMate"
$userData = Join-Path $env:LOCALAPPDATA "TidyMate"
$report = [ordered]@{
    started_at   = (Get-Date).ToString("o")
    msi          = $Msi
    is_admin     = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    installed    = $false
    files        = @()
    shortcuts    = @()
    arp          = @()
    cli_version  = $null
    gui_started  = $false
    user_data_before = (Test-Path $userData)
    uninstall    = @{}
    errors       = @()
}

function Add-Error([string]$message) {
    $report.errors += $message
}

if (-not $report.is_admin) {
    Add-Error "not running elevated; per-machine install will fail with 1603/1925"
}

try {
    if (-not $SkipInstall) {
        $p = Start-Process msiexec.exe -ArgumentList @('/i', "`"$Msi`"", '/qn', '/l*v', "$env:TEMP\tm-vm-install.log") -Wait -PassThru
        if ($p.ExitCode -ne 0) { Add-Error "install exit=$($p.ExitCode)" }
    }

    $report.installed = Test-Path $installPath
    if (Test-Path $installPath) {
        $report.files = @(Get-ChildItem $installPath -Recurse -File | ForEach-Object {
            [ordered]@{ path = $_.FullName.Substring($installPath.Length); bytes = $_.Length }
        })
        $cli = Join-Path $installPath "cli\tidymate.exe"
        if (Test-Path $cli) {
            $report.cli_version = (& $cli --version) -join " "
        }
    }

    if (Test-Path $menuPath) {
        $shell = New-Object -ComObject WScript.Shell
        $report.shortcuts = @(Get-ChildItem $menuPath -Filter *.lnk | ForEach-Object {
            $s = $shell.CreateShortcut($_.FullName)
            [ordered]@{ name = $_.Name; target = $s.TargetPath; exists = (Test-Path $s.TargetPath) }
        })
    }

    $report.arp = @(Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" |
        Where-Object { $_.DisplayName -eq "TidyMate" } |
        ForEach-Object { [ordered]@{ version = $_.DisplayVersion; product_code = $_.PSChildName } })

    # GUI smoke: start it, wait, confirm it is alive, then close it.
    $gui = Join-Path $installPath "TidyMate.exe"
    if (Test-Path $gui) {
        $proc = Start-Process $gui -PassThru
        Start-Sleep -Seconds 6
        $report.gui_started = -not $proc.HasExited
        if (-not $proc.HasExited) { $proc.CloseMainWindow() | Out-Null; Start-Sleep -Seconds 2; if (-not $proc.HasExited) { $proc.Kill() } }
    }

    # Uninstall and verify the user data survives.
    $codes = @($report.arp | ForEach-Object { $_.product_code })
    foreach ($code in $codes) {
        $p = Start-Process msiexec.exe -ArgumentList @('/x', $code, '/qn', '/l*v', "$env:TEMP\t-m-uninstall-$($code.Trim('{}')).log") -Wait -PassThru
        $report.uninstall[$code] = $p.ExitCode
    }
    $report.uninstall["program_left"] = Test-Path $installPath
    $report.uninstall["menu_left"] = Test-Path $menuPath
    $report.uninstall["arp_left"] = @(Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" |
        Where-Object { $_.DisplayName -eq "TidyMate" }).Count
    $report.uninstall["user_data_after"] = Test-Path $userData
}
catch {
    Add-Error $_.Exception.Message
}
finally {
    $report.finished_at = (Get-Date).ToString("o")
    $json = $report | ConvertTo-Json -Depth 6
    $out = Join-Path $env:TEMP "tidymate-vm-verify.json"
    $json | Set-Content -Path $out -Encoding UTF8
    Write-Host "report: $out"
    Write-Host $json
}
