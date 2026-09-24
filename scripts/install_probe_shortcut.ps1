<#
.SYNOPSIS
    Put a "DN2 MIDI Probe" shortcut on the desktop.

.DESCRIPTION
    Idempotent: re-running it overwrites the shortcut with current paths, so
    it is also the way to repair one after the repository moves.

    The shortcut points at `midi_live_launch.ps1`, which kills any running
    probe before starting a new one -- so double-clicking it twice is safe and
    always leaves exactly one probe running.

.PARAMETER Remove
    Delete the shortcut instead of creating it.
#>

[CmdletBinding()]
param(
    [string] $Name = 'DN2 MIDI Probe',
    [switch] $Remove
)

$ErrorActionPreference = 'Stop'

$launcher = Join-Path $PSScriptRoot 'midi_live_launch.ps1'
if (-not (Test-Path $launcher)) { throw "launcher not found: $launcher" }

$desktop = [Environment]::GetFolderPath('Desktop')
$link    = Join-Path $desktop "$Name.lnk"

if ($Remove) {
    if (Test-Path $link) { Remove-Item $link -Force; Write-Host "  removed $link" }
    else                 { Write-Host "  nothing at $link" }
    return
}

$pwsh = (Get-Command powershell.exe).Source

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath       = $pwsh
$sc.Arguments        = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`""
$sc.WorkingDirectory = Split-Path -Parent $PSScriptRoot
$sc.Description      = 'Kill any running DN2 MIDI probe and start a fresh one'
$sc.IconLocation     = "$env:SystemRoot\System32\SHELL32.dll,138"
$sc.Save()

Write-Host "  created $link"
Write-Host "  -> $pwsh $($sc.Arguments)"
