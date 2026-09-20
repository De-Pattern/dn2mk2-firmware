@echo off
rem Install digikit's ColdfireEMAC Ghidra language on Windows.
rem
rem   ghidra\install-coldfire-emac.bat [path to digikit checkout]
rem
rem WHY THIS MATTERS, and it is not a convenience.
rem
rem Stock Ghidra's 68000:BE:32:Coldfire has NO CONSTRUCTOR FOR movclr.l ACCy,Rx.
rem The words a1c0 a3c1 a5c2 a7c3 -- which appear in this firmware's interrupt
rem handler prologues and all through the modulation kernel at 0x400db1dc --
rem decode as bad instructions, and Ghidra's flow analysis STOPS THERE. Every
rem decompilation this project has done of the frame ISR and the modulation
rem module has therefore been silently truncated, with no error to notice.
rem
rem m-dwyer/digikit built a corrected language, 68000:BE:32:ColdfireEMAC, from
rem stock 12.1.3 plus fixes for movclr.l, move.l ACCy,ACCx, MAC and MSAC with
rem load selecting the wrong accumulator (CFPRM p.6-4), and operand order on
rem move.l Ry,ACCx. Its own README is the reference. This script is only the
rem Windows half of their install-coldfire-emac.sh, which assumes Homebrew
rem paths and a symlink; Windows gets a copy instead.
rem
rem The module is THEIRS and is not vendored into this repository -- it is read
rem from a digikit checkout. digikit is MIT (see THIRD-PARTY.md); the language
rem files it derives from Ghidra carry Apache-2.0 and its own LICENSE.txt.
rem
rem Ghidra must be the version the module was built for. Both projects are on
rem 12.1.3. The user settings folder name contains the version, so re-run this
rem after a Ghidra upgrade.
setlocal

if "%GHIDRA_HOME%"=="" (
  for /d %%D in ("C:\Tools\ghidra_*") do set "GHIDRA_HOME=%%D"
)
if "%GHIDRA_HOME%"=="" (
  echo Ghidra not found. Set GHIDRA_HOME, or unpack under C:\Tools\ghidra_*. 1>&2
  exit /b 1
)

set "DIGIKIT=%~1"
if "%DIGIKIT%"=="" set "DIGIKIT=D:_Code\Z_Personal\digikit"
set "MOD=%DIGIKIT%\tools\ghidra\ColdfireEMAC"

if not exist "%MOD%\data\languages\coldfire_emac.slaspec" (
  echo Module not found at "%MOD%". 1>&2
  echo Pass the digikit checkout as the first argument. 1>&2
  exit /b 1
)

rem Ghidra's application.properties gives the version and release name; the
rem user settings folder is ghidra_<version>_<release>.
for /f "tokens=2 delims==" %%V in ('findstr /b "application.version=" "%GHIDRA_HOME%\Ghidra\application.properties"') do set "VER=%%V"
for /f "tokens=2 delims==" %%R in ('findstr /b "application.release.name=" "%GHIDRA_HOME%\Ghidra\application.properties"') do set "REL=%%R"
if "%VER%"=="" (
  echo Could not read application.version from "%GHIDRA_HOME%". 1>&2
  exit /b 1
)
echo Ghidra %VER% %REL% at %GHIDRA_HOME%

echo Compiling coldfire_emac.slaspec ...
call "%GHIDRA_HOME%\support\sleigh.bat" "%MOD%\data\languages\coldfire_emac.slaspec"
if errorlevel 1 (
  echo sleigh failed. 1>&2
  exit /b 1
)
if not exist "%MOD%\data\languages\coldfire_emac.sla" (
  echo sleigh reported success but no .sla was produced. 1>&2
  exit /b 1
)

set "EXT=%APPDATA%\ghidra\ghidra_%VER%_%REL%\Extensions\ColdfireEMAC"
echo Installing to %EXT%
if exist "%EXT%" rmdir /s /q "%EXT%"
mkdir "%EXT%" 2>nul
xcopy /e /i /q /y "%MOD%\data" "%EXT%\data" >nul
copy /y "%MOD%\Module.manifest" "%EXT%\" >nul
if exist "%MOD%\LICENSE.txt" copy /y "%MOD%\LICENSE.txt" "%EXT%\" >nul
if exist "%MOD%\README.md" copy /y "%MOD%\README.md" "%EXT%\" >nul

> "%EXT%\extension.properties" echo name=ColdfireEMAC
>> "%EXT%\extension.properties" echo description=ColdFire language with MOVCLR and corrected EMAC instructions (from m-dwyer/digikit)
>> "%EXT%\extension.properties" echo author=digitakt2
>> "%EXT%\extension.properties" echo createdOn=
>> "%EXT%\extension.properties" echo version=%VER%

echo.
echo Installed 68000:BE:32:ColdfireEMAC
echo Use it by passing -processor 68000:BE:32:ColdfireEMAC to analyze.bat,
echo and RE-IMPORT the image -- changing the language on an existing program
echo does not re-disassemble what the old one got wrong.
endlocal
