<#
.SYNOPSIS
Read-only readiness checks and presentation evidence for the existing local demo.
.EXAMPLE
.\infra\scripts\demo_preflight.ps1 -ShowDatabase
.EXAMPLE
.\infra\scripts\demo_preflight.ps1 -StartExisting -ShowDatabase
#>
[CmdletBinding()]
param(
    [switch]$StartExisting,
    [switch]$ShowDatabase,
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$ProjectName = 'aurafind-phase0',
    [string]$ApiUrl = 'http://localhost:18080',
    [string]$WebUrl = 'http://localhost:13000',
    [string]$StorageUrl = 'http://localhost:19000',
    [string]$MailUrl = 'http://localhost:18025'
)
$ErrorActionPreference = 'Stop'

function Invoke-DemoDocker {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed: docker $($DockerArgs -join ' ')" }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is not available.' }
Invoke-DemoDocker -DockerArgs @('info', '--format', '{{.ServerVersion}}')

if ($StartExisting) {
    # Start existing named containers only: no build, migration, import or reseed.
    foreach ($group in @(@('postgres', 'minio', 'mailhog'), @('ai-worker', 'index-worker'), @('core-api', 'frontend'))) {
        $names = @($group | ForEach-Object { "$ProjectName-$_-1" })
        Invoke-DemoDocker -DockerArgs (@('start') + $names)
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        try {
            $ready = Invoke-RestMethod "$ApiUrl/health/ready" -TimeoutSec 5
            if ($ready.status -eq 'ok') { break }
        } catch { Write-Host 'Waiting for API/model readiness...' }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Readiness timeout. Check ai-worker/core-api logs; no data was reset.' }
        Start-Sleep -Seconds 3
    } while ($true)
}

Write-Host "`nCONTAINERS (seed/migrate Exited 0 is normal)"
Invoke-DemoDocker -DockerArgs @('ps', '-a', '--filter', "label=com.docker.compose.project=$ProjectName", '--format', 'table {{.Names}}\t{{.Status}}\t{{.Ports}}')

foreach ($probe in @(
    @{ Name = 'API readiness'; Url = "$ApiUrl/health/ready" },
    @{ Name = 'Storefront'; Url = "$WebUrl/" },
    @{ Name = 'MinIO'; Url = "$StorageUrl/minio/health/live" },
    @{ Name = 'MailHog'; Url = "$MailUrl/" }
)) {
    $response = Invoke-WebRequest $probe.Url -TimeoutSec 20 -UseBasicParsing
    Write-Host "PASS $($probe.Name): HTTP $($response.StatusCode)"
}

Write-Host "`nSERVING MODEL / INDEX (from runtime, not local training config)"
$config = Invoke-RestMethod "$ApiUrl/api/search/config" -TimeoutSec 20
$config | Select-Object active_index_version, catalog_source, model_kind, num_products, num_vectors, supported_dims, search_mode_default, commerce_data_note | Format-List

$catalog = Invoke-RestMethod "$ApiUrl/api/products?limit=1" -TimeoutSec 20
if (-not $catalog.data -or $catalog.pagination.total -lt 1) { throw 'Catalog is empty.' }
$product = $catalog.data[0]
$image = Invoke-WebRequest $product.image_url -Method Head -TimeoutSec 20 -UseBasicParsing
Write-Host "PASS catalog: $($catalog.pagination.total) products; sample image HTTP $($image.StatusCode)"
Write-Host "Sample detail: $WebUrl/product/$($product.handle)"
Write-Host "Sample MinIO image: $($product.image_url)"

if ($ShowDatabase) {
    Write-Host "`nDATABASE EVIDENCE (read-only; no credentials or customer details)"
    $sql = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'demo_evidence.sql') -Raw
    $sql | & docker exec -i "$ProjectName-postgres-1" psql -X -U aurafind -d aurafind -v ON_ERROR_STOP=1 -P pager=off
    if ($LASTEXITCODE -ne 0) { throw 'Database evidence query failed.' }
}

Write-Host "`nPreflight passed. This checks availability/data, not every authenticated workflow."
Write-Host 'No build, reseed, index rebuild, checkout or model change was performed.'
