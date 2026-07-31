"""Command classification and policy enforcement for Nexus."""

from __future__ import annotations

import re

from mcp_server.models import RiskLevel

DESTRUCTIVE = [
    r"\brm\s+-[^\n]*r[^\n]*f[^\n]*\s+/(?:\s|$)",
    r"\bmkfs(?:\.|\s)",
    r"\bdd\s+if=",
    r"\bformat\s+[a-z]:",
    r"\bRemove-Item\b[^\n]*-Recurse[^\n]*-Force",
    r"\b(drop|truncate)\s+(database|table)\b",
]

PRIVILEGED = [
    r"\b(sudo|su)\b",
    r"\b(iptables|nft|ufw|firewall-cmd)\b",
    r"\b(systemctl|service)\s+(enable|disable|restart|stop|start)\b",
    r"\b(uci\s+(set|delete|commit)|opkg\s+(install|remove))\b",
    r"\b(reg\s+add|schtasks\s+/(create|delete|change))\b",
]

MUTATING = [
    r"\b(mv|cp|mkdir|touch|chmod|chown)\b",
    r"\b(git\s+(commit|push|reset|checkout|merge|rebase))\b",
    r"\b(docker|podman)\s+(run|rm|restart|stop|start|compose)\b",
    r"\b(Set-Content|Add-Content|Copy-Item|Move-Item|New-Item)\b",
]

CROSS_NODE = [
    r"\bssh(?:\.exe)?\b",
    r"\bscp(?:\.exe)?\b",
    r"\brsync\b[^\n]*@",
    r"https?://[^\s]+/(?:rest/v1/)?commands\b",
]


def _matches(patterns: list[str], command: str) -> bool:
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in patterns)


def classify_command(command: str) -> RiskLevel:
    if _matches(DESTRUCTIVE, command):
        return RiskLevel.destructive
    if _matches(PRIVILEGED, command):
        return RiskLevel.privileged
    if _matches(MUTATING, command):
        return RiskLevel.mutating
    return RiskLevel.read_only


def validate_command(
    command: str,
    *,
    allow_privileged: bool = False,
    allow_destructive: bool = False,
    allow_cross_node: bool = False,
) -> tuple[bool, str, RiskLevel]:
    if not command or not command.strip():
        return False, "Command is empty", RiskLevel.read_only
    risk = classify_command(command)
    if _matches(CROSS_NODE, command) and not allow_cross_node:
        return False, "Cross-node execution is forbidden; target the destination Agent directly", risk
    if risk is RiskLevel.destructive and not allow_destructive:
        return False, "Destructive command requires explicit confirmation", risk
    if risk is RiskLevel.privileged and not allow_privileged:
        return False, "Privileged command requires explicit authorization", risk
    return True, "OK", risk
