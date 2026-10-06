@echo off
rem Run CTest on the build made by build.bat (pass "debug" for the Debug build).
setlocal
set "VS=C:\Program Files\Microsoft Visual Studio\18\Community"
set "CFG=Release"
if /i "%~1"=="debug" set "CFG=Debug"
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set "PATH=%VS%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;%PATH%"
ctest --test-dir "%~dp0..\build\%CFG%" --output-on-failure
