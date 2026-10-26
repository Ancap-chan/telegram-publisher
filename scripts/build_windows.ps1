$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Не найден Python проекта: $Python. Сначала создай виртуальное окружение по инструкции в README.md."
}

Push-Location $ProjectRoot
try {
    & $Python -m pip install -e ".[dev,build]"
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось установить зависимости для сборки. Код завершения: $LASTEXITCODE"
    }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "Telegram Publisher" `
        --paths "src" `
        --collect-all webview `
        --collect-all clr_loader `
        --collect-all pythonnet `
        "run_app.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Сборка PyInstaller завершилась с ошибкой. Код завершения: $LASTEXITCODE"
    }

    Write-Host "Сборка завершена. Исполняемый файл: $ProjectRoot\dist\Telegram Publisher\Telegram Publisher.exe"
}
finally {
    Pop-Location
}
