param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [string]$Username = "admin",
    [string]$Password = "admin123"
)

$ErrorActionPreference = "Stop"
$health = Invoke-RestMethod -Uri "$BaseUrl/api/health"
$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
$login = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -ContentType "application/json" -Body $loginBody
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$documents = Invoke-WebRequest -Uri "$BaseUrl/api/documents?page=1&page_size=1" -Headers $headers
$metrics = Invoke-WebRequest -Uri "$BaseUrl/metrics"
$hasMetric = $metrics.Content -match "knowledge_http_requests_total"

[pscustomobject]@{
    service = $health.service
    status = $health.status
    user = $login.user.username
    documents_status = [int]$documents.StatusCode
    total_documents = $documents.Headers["X-Total-Count"]
    metrics_status = [int]$metrics.StatusCode
    metrics_present = $hasMetric
} | ConvertTo-Json

if ($health.status -ne "ok" -or $documents.StatusCode -ne 200 -or $metrics.StatusCode -ne 200 -or -not $hasMetric) {
    throw "demo smoke check failed"
}
