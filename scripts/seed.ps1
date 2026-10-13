# Принудительно выставляем UTF-8 для всех потоков сессии
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==> Checking unvectorized records..." -ForegroundColor Cyan

$ids = @(docker exec -i govtech_postgres psql -U postgres -d govtech_db -t -A -c "SELECT id FROM gov_regulations WHERE embedding IS NULL ORDER BY id ASC;") | 
    ForEach-Object { $_.Trim() } | 
    Where-Object { $_ -match '^\d+$' }

if ($ids.Count -eq 0) {
    Write-Host "All records already have embeddings." -ForegroundColor Green
    exit
}

foreach ($id in $ids) {
    # Читаем текст статьи
    $text = docker exec -i govtech_postgres psql -U postgres -d govtech_db -t -A -c "SELECT title || '. ' || content FROM gov_regulations WHERE id = $id;"
    $cleanText = ($text | Out-String).Trim()

    # Контрольный вывод первых 45 символов
    $preview = $cleanText.Substring(0, [Math]::Min(45,$cleanText.Length))
    Write-Host "ID $id [$preview...] " -NoNewline

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
            docker exec -i govtech_postgres psql -U postgres -d govtech_db -c "UPDATE gov_regulations SET embedding = '$vectorString' WHERE id = $id;" | Out-Null
            Write-Host "[OK]" -ForegroundColor Green
        }
    } catch {
        Write-Host "[ERR: $($_.Exception.Message)]" -ForegroundColor Red
    }
}

Write-Host "`n==> Re-indexing finished." -ForegroundColor Yellow