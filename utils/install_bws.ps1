$url = "https://github.com/bitwarden/sdk-sm/releases/download/bws-v1.0.0/bws-x86_64-pc-windows-msvc-1.0.0.zip"
$zipFile = "C:\Users\Bing\bws.zip"
$extractPath = "C:\Users\Bing\bws"

Write-Host "Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zipFile
Expand-Archive -Path $zipFile -DestinationPath $extractPath -Force
Remove-Item $zipFile

# Add to current process PATH
$env:PATH += ";$extractPath"

# Add to user environment PATH
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$extractPath*") {
    [Environment]::SetEnvironmentVariable("PATH", $userPath + ";$extractPath", "User")
}

Write-Host "bws downloaded and added to User PATH"
