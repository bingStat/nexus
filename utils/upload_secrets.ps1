$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$projectId = "ee0d0f20-b237-45af-b6a5-b49700d66807"
$envFile = "C:\Users\Bing\aurora\Workstation\DigitalDesk\ThinkCenter\.ai\credentials.env"
$bws = "C:\Users\Bing\bws\bws.exe"

$lines = Get-Content $envFile
foreach ($line in $lines) {
    if ($line.Trim() -eq "" -or $line.StartsWith("#")) {
        continue
    }
    
    $index = $line.IndexOf("=")
    if ($index -gt 0) {
        $key = $line.Substring(0, $index).Trim()
        $val = $line.Substring($index + 1).Trim()
        
        # Remove surrounding quotes if they exist
        if ($val.StartsWith("`"") -and $val.EndsWith("`"")) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        
        Write-Host "Uploading $key..."
        
        # Escape value for JSON string
        $valEscaped = $val -replace '\\', '\\' -replace '"', '\"' -replace '`n', '\n'
        
        # We can pass name, value, projectId as arguments
        # Wait, bws secret create uses args: <NAME> <VALUE> <PROJECT_ID>
        # Let's check: bws secret create --help
        $out = & $bws secret create $key $val $projectId
        if ($LASTEXITCODE -eq 0) {
            Write-Host " -> OK"
        } else {
            Write-Host " -> FAILED"
        }
    }
}
