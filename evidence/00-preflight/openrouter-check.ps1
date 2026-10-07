# PRE-01 OpenRouter credential validation — NON-BILLABLE.
# Calls only GET /api/v1/key (key metadata). No model is invoked.
# Reads OPENROUTER_API_KEY from the environment or the git-ignored .env. Never prints the key.
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$key = $env:OPENROUTER_API_KEY
$envFile = Join-Path $root '.env'
if (-not $key -and (Test-Path $envFile)) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*OPENROUTER_API_KEY\s*=\s*(.*?)\s*$') { $key = $Matches[1].Trim('"', "'") }
    }
}
if (-not $key) { 'RESULT: NO_CREDENTIALS (OPENROUTER_API_KEY not provided)'; exit 2 }

'## GET https://openrouter.ai/api/v1/key'
try {
    $k = (Invoke-RestMethod -Uri 'https://openrouter.ai/api/v1/key' -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 20).data
    'http=200'
    # Only non-secret fields are printed; 'label' is omitted because it may contain a key fragment.
    foreach ($f in 'limit', 'limit_remaining', 'limit_reset', 'usage', 'is_free_tier', 'is_provisioning_key') {
        if ($k.PSObject.Properties.Name -contains $f) { "$f=$($k.$f)" }
    }
    'models_invoked=none'
    'RESULT: CREDENTIAL_VALID'
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'n/a' }
    "http=$code"
    'RESULT: CREDENTIAL_INVALID_OR_UNREACHABLE'
    exit 1
}
