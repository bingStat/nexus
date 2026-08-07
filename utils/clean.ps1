param([switch]$DryRun)
$root=Split-Path -Parent $PSScriptRoot
$targets=@(".playwright-mcp",".wrangler")
$targets+=Get-ChildItem $root -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue|ForEach-Object FullName
foreach($target in $targets){$path=if([IO.Path]::IsPathRooted($target)){$target}else{Join-Path $root $target};if(Test-Path $path){if($DryRun){"[DRY-RUN] $path"}else{Remove-Item $path -Recurse -Force;"[REMOVED] $path"}}}
