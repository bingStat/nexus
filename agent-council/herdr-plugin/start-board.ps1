param(
    [string]$Repo = 'C:\Users\Bing\aurora\Workstation\Nexus',
    [string]$TaskId = $env:NEXUS_WEB_COUNCIL_TASK_ID,
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
function Resolve-WebCouncilTask {
    param([string]$Repo,[string]$TaskId)
    if ($TaskId) {
        return [pscustomobject]@{ Repo=$Repo; TaskId=$TaskId }
    }
    $rooms = Join-Path $env:LOCALAPPDATA 'Nexus\agent-council\rooms'
    $state = Get-ChildItem $rooms -Filter state.json -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like '*\web\state.json' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $state) { throw 'No Web Council task found. Run council.ps1 web-start first or set NEXUS_WEB_COUNCIL_TASK_ID.' }
    $data = Get-Content $state.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    return [pscustomobject]@{ Repo=[string]$data.repo; TaskId=[string]$data.task_id }
}

$resolved = Resolve-WebCouncilTask -Repo $Repo -TaskId $TaskId
$Root = Split-Path -Parent $PSScriptRoot
$Council = Join-Path $Root 'council.ps1'
powershell.exe -NoProfile -NoExit -File $Council web-serve -Repo $resolved.Repo -TaskId $resolved.TaskId -Port $Port
