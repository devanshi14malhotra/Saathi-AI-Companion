param(
    [Parameter(Position=0)][string]$Target = "help",
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$Root\backend"
$Python = "$Root\backend\.venv\Scripts\python.exe"
$Pytest = "$Root\backend\.venv\Scripts\pytest.exe"

switch ($Target) {
    "backend" {
        & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    }
    "frontend" {
        npm --prefix "$Root\web" run dev
    }
    "streamlit" {
        & $Python -m streamlit run "$Root\streamlit_app\app.py" @Rest
    }
    "test" {
        $env:LLM_PROVIDER = "stub"
        $env:SAATHI_ENV = "eval"
        & $Pytest "$Root\backend\tests" -v @Rest
    }
    "scenarios" {
        $env:LLM_PROVIDER = "stub"
        $env:SAATHI_ENV = "eval"
        & $Python -m app.eval.harness --cmd scenarios
    }
    "eval" {
        $env:LLM_PROVIDER = "stub"
        $env:SAATHI_ENV = "eval"
        & $Python -m app.eval.harness --cmd eval @Rest
    }
    "trust" {
        $env:LLM_PROVIDER = "stub"
        $env:SAATHI_ENV = "eval"
        & $Python -m app.eval.harness --cmd trust
    }
    "reset" {
        & $Python -m app.eval.harness --cmd reset
    }
    "sarvam-smoke" {
        & $Python "$Root\scripts\sarvam_smoke.py"
    }
    default {
        Write-Host "Usage: .\make.ps1 [backend|frontend|test|scenarios|eval|trust|reset|sarvam-smoke]"
    }
}

