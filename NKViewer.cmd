@echo off

set /a savereq=0
cd %~dp0
set "applock=nkv.lock"
set "verstr=1.1"
TITLE NK Viewer v%verstr%
cls
if exist "%applock%" (
    echo RecipeApp already running!
    echo.
    echo If this is a mistake, you may not have
    echo shutdown a session properly. Please
    echo delete '%applock%' to fix.
    echo.
    pause
    exit /b
)
echo Please wait...
echo.
if NOT exist "%~dp0python\Scripts\pip.exe" (
	%~dp0python\python.exe "%~dp0python\get-pip.py" --no-warn-script-location
)
cls
echo Please wait...
if NOT exist "%~dp0.nk\" (
	%~dp0python\python.exe -m pip install virtualenv --no-warn-script-location
	%~dp0python\python.exe -m virtualenv .nk
	call .nk\Scripts\activate
	python -m pip cache purge
) else (
	rem Just incase, error prevention
	call .nk\Scripts\deactivate
	call .nk\Scripts\activate
)
cls
python -m pip install --upgrade pip
echo running > "%applock%"
cls
python "%~dp0nkv.py"
echo.
if %savereq% == 1 (
	python -m pip freeze > "%~dp0requirements.txt"
)
del "%applock%"
call .nk\Scripts\deactivate
rem echo.
echo It is now safe to close this window
pause >nul
exit /b
