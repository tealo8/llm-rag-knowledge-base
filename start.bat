@echo off
chcp 65001 >nul
set "KNOWLEDGE_START_SCRIPT=%~f0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$raw = [IO.File]::ReadAllText($env:KNOWLEDGE_START_SCRIPT); $body = ($raw -split ':__POWERSHELL_START__')[-1]; $temp = Join-Path $env:TEMP ('knowledge-start-' + [guid]::NewGuid().ToString('N') + '.ps1'); [IO.File]::WriteAllText($temp, $body, [Text.UTF8Encoding]::new($true)); Write-Output $temp" > "%TEMP%\knowledge-start-path.txt"
if errorlevel 1 (
  echo [知域] 无法准备 Windows 启动脚本。
  pause
  goto :eof
)
set /p "KNOWLEDGE_START_TEMP=" < "%TEMP%\knowledge-start-path.txt"
del /q "%TEMP%\knowledge-start-path.txt" >nul 2>nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%KNOWLEDGE_START_TEMP%"
set "KNOWLEDGE_START_EXIT=%ERRORLEVEL%"
del /q "%KNOWLEDGE_START_TEMP%" >nul 2>nul
set "KNOWLEDGE_START_SCRIPT="
set "KNOWLEDGE_START_TEMP="
if not "%KNOWLEDGE_START_EXIT%"=="0" pause
goto :eof

:__POWERSHELL_START__
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $env:KNOWLEDGE_START_SCRIPT
$backendProcess = $null
$frontendProcess = $null
$frontendInputPath = $null
$exitCode = 0
$originalTreatControlCAsInput = $null
$controlCModeChanged = $false

function Write-Step([string]$message) {
    Write-Host "[知域] $message" -ForegroundColor Cyan
}

function Test-PortListening([int]$port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $port)
        return $task.Wait(300) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Test-PortAvailable([int]$port) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        try { $listener.Stop() } catch { }
    }
}

function Find-AvailablePort([int]$startPort, [int]$maxAttempts = 100) {
    for ($offset = 0; $offset -lt $maxAttempts; $offset++) {
        $candidate = $startPort + $offset
        if (-not (Test-PortListening $candidate) -and (Test-PortAvailable $candidate)) { return $candidate }
    }
    throw "从端口 $startPort 开始连续检查 $maxAttempts 个端口，均不可用。"
}

function Stop-ProcessTree($process, [string]$name) {
    if ($null -eq $process) { return }
    try {
        if (-not $process.HasExited) {
            Write-Step "正在停止${name}进程..."
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    } catch {
        Write-Host "[知域] ${name}进程可能已经退出。" -ForegroundColor DarkYellow
    }
}

try {
    Set-Location -LiteralPath $projectRoot
    Write-Step "项目目录：$projectRoot"

    if (-not (Test-Path -LiteralPath ".env")) {
        if (-not (Test-Path -LiteralPath ".env.example")) {
            throw "未找到 .env 和 .env.example，无法启动。"
        }
        Write-Host "[知域] 未找到 .env，正在从 .env.example 创建。请按需修改模型和密钥配置。" -ForegroundColor Yellow
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
    }

    $pythonCommand = $null
    $pythonPrefix = @()
    $pythonCandidates = @(
        [pscustomobject]@{ Command = "py"; Args = @("-3") },
        [pscustomobject]@{ Command = "python3"; Args = @() },
        [pscustomobject]@{ Command = "python"; Args = @() }
    )
    foreach ($candidate in $pythonCandidates) {
        $resolved = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if ($null -eq $resolved) { continue }
        & $resolved.Source @($candidate.Args) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $resolved.Source
            $pythonPrefix = @($candidate.Args)
            break
        }
    }
    if ($null -eq $pythonCommand) {
        throw "未检测到 Python 3.10 或更高版本。请安装后重新运行。"
    }
    $pythonVersion = & $pythonCommand @pythonPrefix -c "import platform; print(platform.python_version())"
    Write-Step "Python $pythonVersion 检测通过。"

    $node = Get-Command "node" -ErrorAction SilentlyContinue
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $node -or $null -eq $npm) {
        throw "未检测到 Node.js/npm。请安装 Node.js 20.19+ 或 22.12+ 后重新运行。"
    }
    & $node.Source -e "const [a,b]=process.versions.node.split('.').map(Number); process.exit((a===20&&b>=19)||(a===22&&b>=12)||a>22?0:1)"
    if ($LASTEXITCODE -ne 0) {
        throw "当前 Node.js 版本过低。Vite 需要 Node.js 20.19+ 或 22.12+。"
    }
    Write-Step "Node.js $(& $node.Source --version) 检测通过。"

    $backendPort = Find-AvailablePort 8080
    $frontendPort = Find-AvailablePort 5173
    if ($backendPort -ne 8080) {
        Write-Host "[知域] 端口 8080 已占用，后端自动顺延至 $backendPort。" -ForegroundColor Yellow
    }
    if ($frontendPort -ne 5173) {
        Write-Host "[知域] 端口 5173 已占用，前端自动顺延至 $frontendPort。" -ForegroundColor Yellow
    }

    $venvDir = Join-Path $projectRoot "venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Step "未找到 ./venv，正在创建虚拟环境..."
        & $pythonCommand @pythonPrefix -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "创建 Python 虚拟环境失败。" }
    }

    $requirements = Join-Path $projectRoot "backend\requirements.txt"
    if (-not (Test-Path -LiteralPath $requirements)) {
        throw "未找到 backend/requirements.txt。"
    }
    Write-Step "正在安装/校验后端依赖..."
    & $venvPython -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "后端依赖安装失败，请检查网络、Python 版本和 requirements.txt。" }

    $frontendDir = Join-Path $projectRoot "frontend"
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "package.json"))) {
        throw "未找到 frontend/package.json。"
    }
    Push-Location $frontendDir
    try {
        if (-not (Test-Path -LiteralPath "node_modules\.bin\vite.cmd")) {
            Write-Step "正在安装前端依赖..."
            & $npm.Source ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败，请检查网络和 Node.js 版本。" }
        }
        Write-Step "正在构建由 $backendPort 端口托管的前端资源..."
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败，请检查 TypeScript/Vite 输出。" }
    } finally {
        Pop-Location
    }

    Write-Step "正在启动 FastAPI 后端：http://localhost:$backendPort"
    $backendProcess = Start-Process -FilePath $venvPython `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$backendPort") `
        -WorkingDirectory (Join-Path $projectRoot "backend") -NoNewWindow -PassThru

    $backendReady = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        if ($backendProcess.HasExited) { throw "FastAPI 后端启动失败，退出码：$($backendProcess.ExitCode)。" }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/health" -TimeoutSec 2
            if ($health.status -eq "ok") { $backendReady = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $backendReady) { throw "FastAPI 后端 90 秒内未就绪，请检查 .env、Ollama 和控制台日志。" }

    Write-Step "后端已就绪，正在启动前端开发服务器：http://localhost:$frontendPort"
    $frontendCommand = 'set "VITE_API_URL=" && set "VITE_API_PROXY_TARGET=http://127.0.0.1:' + $backendPort + '" && npm.cmd run dev -- --host 127.0.0.1 --port ' + $frontendPort + ' --strictPort'
    $frontendInputPath = Join-Path $env:TEMP ("knowledge-frontend-input-" + [guid]::NewGuid().ToString("N") + ".txt")
    [IO.File]::WriteAllText($frontendInputPath, "")
    $frontendProcess = Start-Process -FilePath $env:ComSpec `
        -ArgumentList @("/d", "/c", $frontendCommand) `
        -WorkingDirectory $frontendDir -RedirectStandardInput $frontendInputPath -NoNewWindow -PassThru

    $frontendReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        if ($frontendProcess.HasExited) { throw "前端开发服务器启动失败，退出码：$($frontendProcess.ExitCode)。" }
        if (Test-PortListening $frontendPort) { $frontendReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $frontendReady) { throw "前端开发服务器 30 秒内未就绪。" }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  知域企业知识库启动成功" -ForegroundColor Green
    Write-Host "  应用地址：http://localhost:$backendPort" -ForegroundColor White
    Write-Host "  开发前端：http://localhost:$frontendPort" -ForegroundColor White
    Write-Host "  API 文档：http://localhost:$backendPort/docs" -ForegroundColor White
    Write-Host "  管理员：admin / admin123" -ForegroundColor White
    Write-Host "  普通成员：engineer / engineer123" -ForegroundColor White
    Write-Host "  只读成员：finance / finance123" -ForegroundColor White
    Write-Host "  按 Ctrl+C 或关闭本启动窗口，可停止前后端进程。" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""

    Start-Process "http://localhost:$backendPort"
    try {
        $originalTreatControlCAsInput = [Console]::TreatControlCAsInput
        [Console]::TreatControlCAsInput = $true
        $controlCModeChanged = $true
    } catch { }

    $stopRequested = $false
    while (-not $backendProcess.HasExited -and -not $frontendProcess.HasExited) {
        if ($controlCModeChanged -and [Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq [ConsoleKey]::C -and ($key.Modifiers -band [ConsoleModifiers]::Control)) {
                $stopRequested = $true
                break
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if ($stopRequested) {
        Write-Step "收到停止命令，正在关闭全部服务。"
    } elseif ($backendProcess.HasExited) {
        throw "FastAPI 后端已意外退出，退出码：$($backendProcess.ExitCode)。"
    } elseif ($frontendProcess.HasExited) {
        throw "前端开发服务器已退出，退出码：$($frontendProcess.ExitCode)。"
    }
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host "[知域] 启动失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[知域] 修复后请重新双击 start.bat。" -ForegroundColor Yellow
} finally {
    if ($controlCModeChanged) {
        try { [Console]::TreatControlCAsInput = $originalTreatControlCAsInput } catch { }
    }
    Stop-ProcessTree $frontendProcess "前端"
    Stop-ProcessTree $backendProcess "后端"
    if ($frontendInputPath -and (Test-Path -LiteralPath $frontendInputPath)) {
        Remove-Item -LiteralPath $frontendInputPath -Force -ErrorAction SilentlyContinue
    }
    Set-Location -LiteralPath $projectRoot
}

exit $exitCode
