# Browser integrations

This directory contains the provider-neutral Nexus task contract.

- `nexus-task-api-openapi.json`: import into a ChatGPT Custom GPT Action. Configure API-key authentication as Bearer using the dedicated connector key stored outside Git.
- `WEB_NEXUS_SYSTEM_PROMPT.md`: shared operating prompt for ChatGPT, Claude, and Gemini.
- Claude: add the private Streamable HTTP MCP URL as a custom connector. The URL is stored locally outside Git.
- Gemini: manual Web Council works now. The same MCP URL is ready for Gemini custom apps where Google exposes that feature to the account/region.

Security boundaries:

- No arbitrary shell or `/api/execute` appears in the public OpenAPI or MCP tools.
- The connector never scrapes provider webpages or reads browser storage.
- High-risk approval is recorded but merge, push, deploy, main-branch mutation, and credential changes are not executed by the connector.
- Never commit connector keys or the private MCP URL.
