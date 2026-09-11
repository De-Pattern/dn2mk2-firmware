@echo off
rem Windows twin of run-gate-f.sh: export a Ghidra linear disassembly of one
rem span so it can be checked against objdump. Same contract, same scripts;
rem this one uses analyzeHeadless.bat because the shell launcher mishandles a
rem Windows JDK path. Ghidra's headless analyzer runs natively on Windows, so
rem no WSL is needed for this half of Gate F -- only objdump still is.
rem
rem   ghidra\run-gate-f.bat <raw.bin> <base> <start> <length> <out.txt>
rem
rem Needs GHIDRA_HOME set, or an unpacked Ghidra under C:\Tools\ghidra_*.
rem -noanalysis is deliberate: objdump does a flat linear sweep, so Ghidra must
rem too, or the comparison asks the two engines different questions.
setlocal

if "%GHIDRA_HOME%"=="" (
  for /d %%D in ("C:\Tools\ghidra_*") do set "GHIDRA_HOME=%%D"
)
if "%GHIDRA_HOME%"=="" (
  echo Ghidra not found. Set GHIDRA_HOME, or unpack under C:\Tools\ghidra_*. 1>&2
  exit /b 1
)

set "BIN=%~1"
set "BASE=%~2"
set "START=%~3"
set "LENGTH=%~4"
set "OUT=%~5"
if "%OUT%"=="" (
  echo usage: run-gate-f.bat ^<raw.bin^> ^<base^> ^<start^> ^<length^> ^<out.txt^> 1>&2
  exit /b 1
)

if "%PROCESSOR%"=="" set "PROCESSOR=68000:BE:32:Coldfire"

set "SCRIPTS=%~dp0"
if "%SCRIPTS:~-1%"=="\" set "SCRIPTS=%SCRIPTS:~0,-1%"
set "PROJECT=%TEMP%\gatef_%RANDOM%"
mkdir "%PROJECT%"

call "%GHIDRA_HOME%\support\analyzeHeadless.bat" "%PROJECT%" gatef ^
  -import "%BIN%" ^
  -processor "%PROCESSOR%" ^
  -loader BinaryLoader ^
  -loader-baseAddr "%BASE%" ^
  -noanalysis ^
  -scriptPath "%SCRIPTS%" ^
  -postScript ExportDisassembly.java "%START%" "%LENGTH%" "%OUT%" ^
  -deleteProject
set "RC=%ERRORLEVEL%"

rmdir /s /q "%PROJECT%" 2>nul
if %RC%==0 echo wrote %OUT%
exit /b %RC%
