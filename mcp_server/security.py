"""
Nexus MCP Command Security and Dangerous Command Interceptor
"""
import re
from typing import Tuple

# Dangerous command patterns regex list
DANGEROUS_PATTERNS = [
    r"\brm\s+-[rf]*\s+/",                 # rm -rf /
    r"\brmdir\s+/s\s+/q",                 # Windows rmdir /s /q
    r"\bdel\s+/[fFqQsS]*\s+[a-zA-Z]:",    # Windows del /f /s /q C:\
    r"\bRemove-Item\s+.*-Recurse",        # PowerShell Remove-Item -Recurse
    r"\bmkfs\b",                           # File system creation
    r"\bformat\s+[a-zA-Z]:",              # Windows disk format
    r"\bshutdown\b",                       # System shutdown
    r"\breboot\b",                         # System reboot
    r"\biptables\s+-F\b",                  # Flush firewall rules
    r"\bufw\s+disable\b",                  # Disable UFW firewall
    r">\s*/dev/sd[a-z]",                   # Raw disk overwrite
    r"\bdd\s+if=",                         # Direct disk write with dd
]

def validate_command(command_str: str, allow_dangerous: bool = False) -> Tuple[bool, str]:
    """
    Validates command against dangerous patterns.
    Returns (is_allowed: bool, reason_message: str).
    """
    if not command_str or not command_str.strip():
        return False, "Error: Command string is empty."

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command_str, re.IGNORECASE):
            if not allow_dangerous:
                return (
                    False,
                    f"Blocked: High-risk command pattern detected matching '{pattern}'. "
                    "If you explicitly intend to run this command, set 'allow_dangerous=True'."
                )
    return True, "OK"

