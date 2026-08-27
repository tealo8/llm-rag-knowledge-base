param(
    [int]$Port = 8080,
    [switch]$SkipBuild
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到 .venv。请先按 README 安装 Python 依赖。"
}

if (-not $SkipBuild) {
    & npm run build --prefix (Join-Path $projectRoot "frontend")
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
}

Push-Location (Join-Path $projectRoot "backend")
try {
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
