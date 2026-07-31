$action = New-ScheduledTaskAction -Execute 'C:\Users\Bing\aurora\Workstation\Nexus\start_nexus_agent.bat'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -MultipleInstances IgnoreNew -Hidden
Register-ScheduledTask -TaskName 'NexusAgent-Victus' -Action $action -Trigger $trigger -Settings $settings -Force -Description 'Nexus distributed cluster agent for victus node.'
Write-Host 'NexusAgent-Victus scheduled task registered.'

