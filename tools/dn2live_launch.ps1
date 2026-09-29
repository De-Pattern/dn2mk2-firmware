<#
.SYNOPSIS
    Kill any running MIDI page or probe client, then start dn2live and open the page.

.DESCRIPTION
    derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

    scripts/midi_live_launch.ps1, for tools/dn2live.py. dn2live holds the
    Digitone II's USB MIDI input AND output, so anything else holding either
    one leaves it deaf or unable to ask the probe: midi_live.py (the public
    page, same HTTP port), a stale dn2live.py, a dn2probe.py left running.
    Those are stopped first, by listening port and by command line, and the
    HTTP port is confirmed free before the new one starts.

    Elektron Transfer and DNX also hold the port; they are not killed here
    (they may be in the middle of something). Close them yourself.

    The server runs in THIS window. Closing the window stops it; the run's
    log is already on disk in out/dn2live/.

.PARAMETER Rate
    STATS requests a second: 10 (default), or 25 / 50 with -NoMidi.
.PARAMETER NoMidi
    Start with the MIDI event view off (allows the faster rates).
.PARAMETER Symbols
    A profiling build's symbols.json (out/<build>/symbols.json): lfo4's timers too.
.PARAMETER MidiIn / MidiOut
    Port indices, if the name match ("Digitone II") is ambiguous. -List shows them.
#>

[CmdletBinding()]
param(
    [int]    $Port    = 8737,
    [double] $Rate    = 10,
    [int]    $MidiIn  = -1,
    [int]    $MidiOut = -1,
    [string] $Name    = 'Digitone II',
    [string] $Symbols = '',
    [switch] $NoMidi,
    [switch] $List,
    [switch] $NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ''
Write-Host '  DN2 live: MIDI and probe' -ForegroundColor Cyan
Write-Host '  ------------------------'

if ($List) {
    & python tools/dn2live.py --list
    Write-Host ''
    Read-Host '  enter to close'
    exit 0
}

function Stop-Holders {
    param([int] $Port)
    $killed = @()
    try {
        $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                  Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
        $owners = @()
    }
    $stale = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
             Where-Object { $_.CommandLine -and $_.CommandLine -match '(midi_live|dn2live|dn2probe)\.py' } |
             Select-Object -ExpandProperty ProcessId
    foreach ($procId in @($owners + $stale | Sort-Object -Unique)) {
        if ($procId -eq $PID) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Stop-Process -Id $procId -Force -ErrorAction Stop
            $killed += "$($p.ProcessName) [$procId]"
        } catch {
        }
    }
    return $killed
}

$killed = Stop-Holders -Port $Port
if ($killed.Count) {
    Write-Host "  stopped: $($killed -join ', ')" -ForegroundColor Yellow
} else {
    Write-Host '  nothing was running'
}

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 200
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "  port $Port is still held after 10s -- not starting." -ForegroundColor Red
    Read-Host '  enter to close'
    exit 1
}

$argv = @('-u', 'tools/dn2live.py', '--http', $Port, '--rate', $Rate, '--port', $Name)
if ($MidiIn -ge 0)  { $argv += @('--in', $MidiIn) }
if ($MidiOut -ge 0) { $argv += @('--out', $MidiOut) }
if ($NoMidi)        { $argv += '--no-midi' }
if ($Symbols)       { $argv += @('--symbols', $Symbols) }

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u) Start-Sleep -Milliseconds 1200; Start-Process $u
    } -ArgumentList "http://127.0.0.1:$Port" | Out-Null
}

Write-Host "  starting on port $Port, $Rate STATS/s" -ForegroundColor Green
Write-Host '  close this window to stop it. Close Transfer and DNX first.'
Write-Host ''

& python @argv

Write-Host ''
Write-Host '  dn2live exited.' -ForegroundColor Yellow
Read-Host '  enter to close'
