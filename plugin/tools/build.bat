@echo off
rem Configure and build the plugin (Ninja, Release by default; pass "debug" for Debug).
setlocal
set "VS=C:\Program Files\Microsoft Visual Studio\18\Community"
set "CFG=Release"
if /i "%~1"=="debug" set "CFG=Debug"
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set "PATH=%VS%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;%VS%\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"
set "ROOT=%~dp0.."
set "BUILD=%ROOT%\build\%CFG%"
cmake -S "%ROOT%" -B "%BUILD%" -G Ninja -DCMAKE_BUILD_TYPE=%CFG% || exit /b 1
cmake --build "%BUILD%" || exit /b 1
echo Build OK: %BUILD%
