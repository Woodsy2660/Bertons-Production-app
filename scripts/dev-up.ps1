# Start Docker Desktop (if needed), Postgres, and the dev server.
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Test-DockerReady {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & docker info *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $old
    }
}

function Wait-Docker {
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerReady) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

Write-Host "Checking Docker..."
if (-not (Test-DockerReady)) {
    $dockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Write-Host "Starting Docker Desktop..."
        Start-Process $dockerExe
        if (-not (Wait-Docker)) {
            Write-Error "Docker Desktop did not become ready within 3 minutes."
        }
    } else {
        Write-Error "Docker Desktop not found. Install Docker Desktop and try again."
    }
}

Write-Host "Starting Postgres..."
docker compose up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for Postgres on port 5433..."
$deadline = (Get-Date).AddMinutes(2)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", 5433)
        $client.Close()
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    Write-Error "Postgres did not accept connections on port 5433."
}

Write-Host "Postgres is up."
Write-Host ""
Write-Host "Start the app in another terminal:"
Write-Host "  python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload"
Write-Host ""
Write-Host "App:    http://127.0.0.1:8001"
Write-Host "Parser: http://127.0.0.1:8001/dev/work-order-parser"