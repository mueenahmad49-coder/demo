@echo off
setlocal
set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=%~dp0..\..\work\python-integrated\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo Create the Python environment using INTEGRATION.md. 1>&2
    exit /b 1
)
pushd "%~dp0" || exit /b 1
"%PROJECT_PYTHON%" %*
set "PROJECT_RESULT=%ERRORLEVEL%"
popd
exit /b %PROJECT_RESULT%
