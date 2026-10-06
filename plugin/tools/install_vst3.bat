@echo off
rem Copy the built VST3 bundle into the per-user VST3 folder (no admin needed).
setlocal
set "CFG=Release"
if /i "%~1"=="debug" set "CFG=Debug"
set "SRC=%~dp0..\build\%CFG%\SnakeOilSynth_artefacts\%CFG%\VST3\SnakeOil Synth.vst3"
set "DEST=%LOCALAPPDATA%\Programs\Common\VST3"
if not exist "%SRC%" (
  echo Bundle not found: %SRC%
  echo Run tools\build.bat first.
  exit /b 1
)
if not exist "%DEST%" mkdir "%DEST%"
robocopy "%SRC%" "%DEST%\SnakeOil Synth.vst3" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Copy failed. Close any host that has the plugin loaded and retry.
  exit /b 1
)
echo Installed to: %DEST%\SnakeOil Synth.vst3
