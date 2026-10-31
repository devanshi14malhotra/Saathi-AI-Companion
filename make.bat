@echo off
setlocal
set PYTHONPATH=%~dp0backend
set PYTHON=%~dp0backend\.venv\Scripts\python.exe
set PYTEST=%~dp0backend\.venv\Scripts\pytest.exe

if "%1"=="backend" (
    "%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    goto :eof
)
if "%1"=="frontend" (
    "%PYTHON%" -m streamlit run "%~dp0streamlit_app\app.py"
    goto :eof
)
if "%1"=="streamlit" (
    "%PYTHON%" -m streamlit run "%~dp0streamlit_app\app.py"
    goto :eof
)
if "%1"=="test" (
    set LLM_PROVIDER=stub
    set SAATHI_ENV=eval
    "%PYTEST%" "%~dp0backend\tests" -v
    goto :eof
)
if "%1"=="scenarios" (
    set LLM_PROVIDER=stub
    set SAATHI_ENV=eval
    "%PYTHON%" -m app.eval.harness --cmd scenarios
    goto :eof
)
if "%1"=="eval" (
    set LLM_PROVIDER=stub
    set SAATHI_ENV=eval
    "%PYTHON%" -m app.eval.harness --cmd eval %2 %3 %4 %5 %6 %7
    goto :eof
)
if "%1"=="trust" (
    set LLM_PROVIDER=stub
    set SAATHI_ENV=eval
    "%PYTHON%" -m app.eval.harness --cmd trust
    goto :eof
)
if "%1"=="reset" (
    "%PYTHON%" -m app.eval.harness --cmd reset
    goto :eof
)
if "%1"=="sarvam-smoke" (
    "%PYTHON%" "%~dp0scripts\sarvam_smoke.py"
    goto :eof
)

echo Usage: .\make.bat [backend^|frontend^|test^|scenarios^|eval^|trust^|reset^|sarvam-smoke]

