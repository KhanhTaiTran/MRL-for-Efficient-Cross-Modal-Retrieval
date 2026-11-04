param([switch]$Build)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $projectRoot
try {
    $composeArgs = @('--env-file', 'infra/fashiongen.env.example', '-f', 'docker-compose.yml', '-f', 'docker-compose.fashiongen.yml')
    function Invoke-Compose {
        & docker compose @composeArgs @args
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE)." }
    }
    if ($Build) { Invoke-Compose build ai-worker core-api frontend }
    Invoke-Compose up -d postgres minio mailhog
    Invoke-Compose run --rm --no-deps migrate
    New-Item -ItemType Directory -Force -Path tmp | Out-Null
    $backupName = 'before-fashiongen-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
    Invoke-Compose exec -T postgres pg_dump -U aurafind -d aurafind --format=custom "--file=/tmp/$backupName"
    Invoke-Compose cp "postgres:/tmp/$backupName" "tmp/$backupName"
    Invoke-Compose stop index-worker
    Invoke-Compose run --rm --no-deps seed
    # A checkpoint change requires a cold start, not same-model live reload.
    Invoke-Compose up -d --no-deps --force-recreate --wait --wait-timeout 240 ai-worker core-api frontend index-worker
    Invoke-Compose ps
    Write-Host 'FashionGen is ready: http://localhost:13000 (API: http://localhost:18080)'
    Write-Host "Database backup: tmp/$backupName"
} finally {
    Pop-Location
}
