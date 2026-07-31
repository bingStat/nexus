$env:NEXUS_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$env:DEVICE_NAME = "victus"
$action = New-ScheduledTaskAction `
    -Execute 'python' `
    -Argument 'C:\Users\Bing\aurora\Workstation\Nexus\agent_v2.py' `
    -WorkingDirectory 'C:\Users\Bing\aurora\Workstation\Nexus'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -RestartCount 999 `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew
$env_nexus_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
Register-ScheduledTask `
    -TaskName 'NexusAgent-Victus' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force `
    -Description "Nexus distributed cluster agent for victus node. Auto-restart on failure."
# Inject env vars into scheduled task via XML
$task = Get-ScheduledTask -TaskName 'NexusAgent-Victus'
$taskXml = $task | Export-ScheduledTask
[xml]$xml = $taskXml
# Add environment variables
$ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
$envNode = $xml.CreateElement("EnvironmentVariables", $ns)
$kv1 = $xml.CreateElement("EnvironmentVariable", $ns)
$name1 = $xml.CreateElement("Name", $ns); $name1.InnerText = "NEXUS_API_KEY"
$val1 = $xml.CreateElement("Value", $ns); $val1.InnerText = $env_nexus_key
$kv1.AppendChild($name1); $kv1.AppendChild($val1)
$kv2 = $xml.CreateElement("EnvironmentVariable", $ns)
$name2 = $xml.CreateElement("Name", $ns); $name2.InnerText = "DEVICE_NAME"
$val2 = $xml.CreateElement("Value", $ns); $val2.InnerText = "victus"
$kv2.AppendChild($name2); $kv2.AppendChild($val2)
$envNode.AppendChild($kv1); $envNode.AppendChild($kv2)
$xml.Task.AppendChild($envNode) | Out-Null
$xmlStr = $xml.OuterXml
Register-ScheduledTask -TaskName 'NexusAgent-Victus' -Xml $xmlStr -Force
Write-Host "NexusAgent-Victus scheduled task registered successfully."
