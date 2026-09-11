@echo off
rem Analyse a raw ColdFire image once and keep the project, so functions and
rem references survive between scripts. Then run post-scripts against it.
rem
rem   ghidra\analyze.bat <project dir> <name> <raw.bin> <base> [postScript args...]
rem
rem Unlike run-gate-f.bat this DOES auto-analyse (no -noanalysis): decompiling
rem needs functions and references, which analysis creates. Gate F must have
rem cleared the disassembler on this image's ISA before anything here is
rem trusted -- see docs/mainos-image.md.
rem
rem Reuses an existing project with -process if <name> is already imported, so
rem a second script does not re-analyse three megabytes.
setlocal

if "%GHIDRA_HOME%"=="" (
  for /d %%D in ("C:\Tools\ghidra_*") do set "GHIDRA_HOME=%%D"
)
if "%GHIDRA_HOME%"=="" (
  echo Ghidra not found. Set GHIDRA_HOME, or unpack under C:\Tools\ghidra_*. 1>&2
  exit /b 1
)

set "PROJDIR=%~1"
set "NAME=%~2"
set "BIN=%~3"
set "BASE=%~4"
if "%PROCESSOR%"=="" set "PROCESSOR=68000:BE:32:Coldfire"
set "SCRIPTS=%~dp0"
if "%SCRIPTS:~-1%"=="\" set "SCRIPTS=%SCRIPTS:~0,-1%"

rem Shift off the first four fixed args; the rest is "-postScript Foo.java ...".
shift & shift & shift & shift
set "REST="
:collect
if "%~1"=="" goto run
set "REST=%REST% "%~1""
shift
goto collect

:run
if exist "%PROJDIR%\%NAME%.gpr" (
  call "%GHIDRA_HOME%\support\analyzeHeadless.bat" "%PROJDIR%" "%NAME%" ^
    -process -noanalysis -scriptPath "%SCRIPTS%" %REST%
) else (
  mkdir "%PROJDIR%" 2>nul
  call "%GHIDRA_HOME%\support\analyzeHeadless.bat" "%PROJDIR%" "%NAME%" ^
    -import "%BIN%" -processor "%PROCESSOR%" -loader BinaryLoader -loader-baseAddr "%BASE%" ^
    -scriptPath "%SCRIPTS%" %REST%
)
exit /b %ERRORLEVEL%
