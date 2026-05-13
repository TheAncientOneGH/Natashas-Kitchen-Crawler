@echo off

set /a savereq=0
cd %~dp0
set "applock=nkc.lock"
set "verstr=1.1"
TITLE NK Crawler v%verstr%
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
%~dp0python\python.exe -m pip cache purge
cls
echo Please wait...
if NOT exist "%~dp0.nk\" (
	%~dp0python\python.exe -m pip install virtualenv --no-warn-script-location
	%~dp0python\python.exe -m virtualenv .nk
	call .nk\Scripts\activate
) else (
	rem Error prevention, just in case
	call .nk\Scripts\deactivate
	call .nk\Scripts\activate
)
cls
echo Please wait...
python -m pip install --upgrade pip
echo running > "%applock%"
cls
python "%~dp0nkc.py" %*
echo.
if %savereq% == 1 (
	python -m pip freeze --local > "%~dp0requirements.txt"
)
del "%~dp0%applock%"
call .nk\Scripts\deactivate
rem echo.
echo It is now safe to close this window
pause >nul
exit /b
