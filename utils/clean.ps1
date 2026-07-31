$base = 'C:\Users\Bing\aurora\Workstation\Nexus'
New-Item -Path $base\deploy -ItemType Directory -Force | Out-Null
New-Item -Path $base\check -ItemType Directory -Force | Out-Null
New-Item -Path $base\tests -ItemType Directory -Force | Out-Null
New-Item -Path $base\utils -ItemType Directory -Force | Out-Null

Move-Item -Path $base\deploy_*.ps1, $base\deploy_*.py -Destination $base\deploy -ErrorAction SilentlyContinue
Move-Item -Path $base\check_*.ps1 -Destination $base\check -ErrorAction SilentlyContinue
Move-Item -Path $base\test_*.ps1 -Destination $base\tests -ErrorAction SilentlyContinue
Move-Item -Path $base\*tc_tunnel*.ps1, $base\*modem*.ps1, $base\*n1*.ps1, $base\*upnp*.py, $base\*secret*.ps1, $base\*docker*.ps1 -Destination $base\utils -ErrorAction SilentlyContinue

$keep = @('agent_v2.py', 'README.md', 'NEXUS_ARCHITECTURE_DESIGN.md', 'nexus_openapi.json', 'nexus_system_prompt.md', 'supabase_init.sql', 'install.ps1', 'install.sh', '.gitignore', 'start_nexus_agent.bat', 'mcp_server', 'deploy', 'check', 'tests', 'utils', 'clean.ps1', '.git', '.ai')

Get-ChildItem $base | Where-Object { $_.Name -notin $keep } | Move-Item -Destination $base\utils -ErrorAction SilentlyContinue
