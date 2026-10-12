Write-Host "==> 1. Checking unvectorized records in PostgreSQL..." -ForegroundColor Cyan

# Fetch IDs without embeddings
$ids = @(docker exec -i govtech_postgres psql -U postgres -d govtech_db -t -A -c "SELECT id FROM gov_regulations WHERE embedding IS NULL ORDER BY id ASC;") | 
    ForEach-Object { $_.Trim() } | 
    Where-Object { $_ -match '^\d+$' }

if ($ids.Count -eq 0) {
    Write-Host "All records are already vectorized." -ForegroundColor Green
    exit
}

Write-Host "Records pending vectorization: $($ids.Count)" -ForegroundColor Yellow

foreach ($id in $ids) {
    Write-Host "Vectorizing record ID $id..." -NoNewline

    # Extract regulation text
    $text = docker exec -i govtech_postgres psql -U postgres -d govtech_db -t -A -c "SELECT title || '. ' || content FROM gov_regulations WHERE id = $id;"
    $cleanText = ($text | Out-String).Trim()

    # Build Ollama payload
    $payload = @{
        model = "bge-m3"
        prompt = $cleanText
    } | ConvertTo-Json -Compress

    $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)

    try {
        $response = Invoke-RestMethod -Uri "http://localhost:11434/api/embeddings" `
            -Method Post `
            -Body $utf8Bytes `
            -ContentType "application/json; charset=utf-8"

        if ($response.embedding -and $response.embedding.Count -gt 0) {
            $vectorString = "[" + ($response.embedding -join ",") + "]"
            
            # Save embedding to PostgreSQL
            docker exec -i govtech_postgres psql -U postgres -d govtech_db -c "UPDATE gov_regulations SET embedding = '$vectorString' WHERE id = $id;" | Out-Null
            Write-Host " [OK] ($($response.embedding.Count) dims)" -ForegroundColor Green
        } else {
            Write-Host " [FAILED: empty vector]" -ForegroundColor Red
        }
    } catch {
        Write-Host " [ERROR: $($_.Exception.Message)]" -ForegroundColor Red
    }
}

Write-Host "`n==> Knowledge base successfully initialized with bge-m3 embeddings!" -ForegroundColor Yellow