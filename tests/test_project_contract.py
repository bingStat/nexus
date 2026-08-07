from __future__ import annotations
import json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_installers_use_distributable_agents():
    sh=(ROOT/'install.sh').read_text(encoding='utf-8')
    ps=(ROOT/'install.ps1').read_text(encoding='utf-8')
    assert 'agent/unix_agent.py' in sh and 'agent/windows_agent.py' in ps
    assert "$AgentCode" not in ps

def test_no_obsolete_queue_contract():
    for name in ('install.sh','install.ps1','AGENTS.md'):
        text=(ROOT/name).read_text(encoding='utf-8')
        assert 'supabase.co/rest/v1' not in text
        assert 'target_device.ilike' not in text

def test_no_embedded_jwt():
    pattern=re.compile(r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}')
    for path in ROOT.rglob('*'):
        if path.is_file() and '.git' not in path.parts and 'docs/evidence' not in path.as_posix():
            try: text=path.read_text(encoding='utf-8')
            except (UnicodeDecodeError,OSError): continue
            assert not pattern.search(text), path

def test_embedded_openapi_is_valid():
    text=(ROOT/'nexus_system_prompt.md').read_text(encoding='utf-8')
    match=re.search(r'```json\s*(\{.*\})\s*```',text,re.S)
    assert match
    spec=json.loads(match.group(1))
    ops={op.get('operationId') for methods in spec['paths'].values() for op in methods.values() if isinstance(op,dict)}
    assert {'listNexusDevices','executeNexusCommand','executeNexusBatch'} <= ops

def test_agents_require_canonical_device_and_single_broker():
    for name in ('unix_agent.py','windows_agent.py'):
        text=(ROOT/'agent'/name).read_text(encoding='utf-8')
        assert 'return [str(config["device_id"])]' in text
        assert 'task = api.broker_claim(config) if' not in text
        assert 'Exactly one regional broker URL is required' in text
