<#
.SYNOPSIS
    Kill any running MIDI probe, then start a fresh one and open the page.

.DESCRIPTION
    The probe holds a Windows MIDI input handle. Two things follow from that,
    and they are the whole reason this script exists rather than a bare
    shortcut to `python midi_live.py`:

      * A second instance cannot take the port while the first still holds it,
        and Windows does not say so loudly -- the newcomer simply hears nothing.
        So the old instance is killed first, and the port is confirmed free
        before the new one starts.

      * A probe left running from a previous session is invisible: no tray
        icon, no window if it was started by a tool. Killing by listening
        port catches it whoever started it.

    The server then runs in THIS window, in the foreground. Closing the window
    stops the probe. That is deliberate: the owner closes the probe, not a
    background task that outlives the work.

.PARAMETER MidiIn
    Index of the MIDI input to listen on. Run with -List to see them.
#>

[CmdletBinding()]
param(
    [int]    $MidiIn = 0,
    [int]    $Port   = 8737,
    [switch] $List,
    [switch] $NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ''
Write-Host '  DN2 MIDI probe' -ForegroundColor Cyan
Write-Host '  --------------'

if ($List) {
    & python scripts/midi_live.py --list
    Write-Host ''
    Read-Host '  enter to close'
    exit 0
}

# --- 1. kill whatever holds the port -------------------------------------

function Stop-Probe {
    param([int] $Port)

    $killed = @()

    # by listening port: catches an instance started by anything, including a
    # previous session's background task with no window of its own
    try {
        $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                  Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
        $owners = @()
    }

    # by command line: catches one that died before binding, or bound elsewhere
    $stale = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
             Where-Object { $_.CommandLine -and $_.CommandLine -match 'midi_live\.py' } |
             Select-Object -ExpandProperty ProcessId

    foreach ($procId in @($owners + $stale | Sort-Object -Unique)) {
        if ($procId -eq $PID) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Stop-Process -Id $procId -Force -ErrorAction Stop
            $killed += "$($p.ProcessName) [$procId]"
        } catch {
            # already gone between the query and the kill -- nothing to report
        }
    }
    return $killed
}

$killed = Stop-Probe -Port $Port
if ($killed.Count) {
    Write-Host "  stopped: $($killed -join ', ')" -ForegroundColor Yellow
} else {
    Write-Host '  nothing was running'
}

# The handle is released by the kernel, not by the dying process, so confirm
# rather than assume. A probe that starts onto a still-held port is deaf.
$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    $still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $still) { break }
    Start-Sleep -Milliseconds 200
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "  port $Port is still held after 10s -- not starting." -ForegroundColor Red
    Read-Host '  enter to close'
    exit 1
}

# --- 2. start a fresh one ------------------------------------------------

if (-not $NoBrowser) {
    # give the server a moment to bind before the browser asks for the page
    Start-Job -ScriptBlock {
        param($u) Start-Sleep -Milliseconds 900; Start-Process $u
    } -ArgumentList "http://127.0.0.1:$Port" | Out-Null
}

Write-Host "  starting on port $Port, MIDI in [$MidiIn]" -ForegroundColor Green
Write-Host '  close this window to stop the probe.'
Write-Host ''

& python -u scripts/midi_live.py --in $MidiIn --port $Port

Write-Host ''
Write-Host '  the probe exited.' -ForegroundColor Yellow
Read-Host '  enter to close'
