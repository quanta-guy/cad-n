param(
    [switch]$Launch
)

$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

Write-Host "== CAD-N check =="
Write-Host "Repo: $repo"
Write-Host "Python: $python"
Write-Host ""

Write-Host "== Running tests =="
& $python -m pytest

Write-Host ""
Write-Host "== Running application selfcheck =="
$oldSelfCheck = $env:CADN_SELFCHECK
try {
    $env:CADN_SELFCHECK = "1"
    & $python -m cad_n
}
finally {
    if ($null -eq $oldSelfCheck) {
        Remove-Item Env:\CADN_SELFCHECK -ErrorAction SilentlyContinue
    }
    else {
        $env:CADN_SELFCHECK = $oldSelfCheck
    }
}

if ($Launch) {
    Write-Host ""
    Write-Host "== Launching CAD-N =="
    & $python -m cad_n
}

Write-Host ""
Write-Host "CAD-N checks passed."
