# AGENTS.md

## Engineering principles

- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability.
- Lean on dependencies already in the project before adding packages or writing replacements.
- Make architectural decisions for the long term. Do not accept temporary stopgaps.

## Nexus project rules

1. The production path is `client -> Global API -> regional broker -> target agent`.
2. The target device never changes during failover.
3. Agents consume regional broker jobs only. Supabase is not an agent task queue.
4. Canonical device IDs are mandatory; aliases, `all`, and `broadcast` are not supported.
5. `agent/unix_agent.py` and `agent/windows_agent.py` are the only distributable agent implementations.
6. Installers download those files; installers must not embed agent source.
7. Linux uses systemd, OpenWrt uses procd, and Windows uses one Scheduled Task.
8. Credentials come from explicit arguments or environment variables and are stored only in restricted configuration files.
9. OpenAPI is published by the production Global API. The prompt embeds the same specification.
10. A change is complete only after syntax checks, tests, health checks, and a real read-only command receipt.
