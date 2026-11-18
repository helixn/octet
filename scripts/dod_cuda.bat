@echo off
REM DoD gate 2 (Windows): compile-check the CUDA skeleton with MSVC env.
REM Locates Visual Studio via vswhere (no hardcoded paths), then nvcc.
setlocal EnableExtensions
cd /d "%~dp0.."

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSINSTALL="
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%i"
)
if "%VSINSTALL%"=="" set "VSINSTALL=C:\Program Files\Microsoft Visual Studio\2022\Community"
if not exist "%VSINSTALL%\VC\Auxiliary\Build\vcvars64.bat" (
    echo ERROR: vcvars64.bat not found under "%VSINSTALL%"
    exit /b 1
)
set VSCMD_SKIP_SENDTELEMETRY=1
call "%VSINSTALL%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
where cl >nul 2>&1
if errorlevel 1 (
    echo ERROR: MSVC environment setup failed
    exit /b 1
)

nvcc -std=c++17 -Wno-deprecated-gpu-targets ^
     -gencode arch=compute_70,code=sm_70 -gencode arch=compute_86,code=sm_86 ^
     -c cuda\octet.cu -o cuda\octet.o
if errorlevel 1 (
    echo ERROR: CUDA compile check FAILED
    exit /b 1
)
del /q cuda\octet.o
echo GATE 2 OK: CUDA compile check passed
exit /b 0
