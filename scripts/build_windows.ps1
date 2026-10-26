$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildVenv = Join-Path $ProjectRoot ".venv-build"
$Python = Join-Path $BuildVenv "Scripts\python.exe"

$Launcher = Get-Command py -ErrorAction SilentlyContinue
if (-not $Launcher) {
    throw "Не найден Python Launcher (команда py). Установи Python 3.11 или новее вместе с Python Launcher."
}

Push-Location $ProjectRoot
try {
    # Пересоздаём только выделенное окружение сборки, не затрагивая .venv разработчика.
    if (Test-Path $BuildVenv) {
        Remove-Item -LiteralPath $BuildVenv -Recurse -Force
    }

    & py -3 -m venv $BuildVenv
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось создать чистое окружение сборки. Код завершения: $LASTEXITCODE"
    }

    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось обновить pip. Код завершения: $LASTEXITCODE"
    }

    & $Python -m pip install -e ".[dev,build]"
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось установить зависимости проекта и сборки. Код завершения: $LASTEXITCODE"
    }

    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Обнаружены несовместимые зависимости. Сборка отменена."
    }

    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "Автоматические тесты не пройдены. Сборка отменена."
    }

    & $Python -m PyInstaller --noconfirm --clean --windowed --name "Telegram Publisher" --paths "src" --collect-all webview --collect-all clr_loader --collect-all pythonnet "run_app.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Сборка PyInstaller завершилась с ошибкой. Код завершения: $LASTEXITCODE"
    }

    & $Python -m pip freeze | Set-Content -Encoding utf8 (Join-Path $ProjectRoot "dist\build-dependencies.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось сохранить список установленных зависимостей."
    }

    $Executable = Join-Path $ProjectRoot "dist\Telegram Publisher\Telegram Publisher.exe"
    $DependencyList = Join-Path $ProjectRoot "dist\build-dependencies.txt"
    Write-Host "Сборка завершена. Исполняемый файл: $Executable"
    Write-Host "Список версий зависимостей: $DependencyList"
}
finally {
    Pop-Location
}
