import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware

from mcp_server.server import mcp

app = FastAPI(
    title="Nexus MCP Server",
    description="MCP Remote Control Hub Endpoint for Nexus Cluster",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    expected_token = os.getenv("NEXUS_MCP_TOKEN", "")
    if expected_token:
        if not credentials or credentials.credentials != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing Authorization Bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Nexus MCP Server", "transport": "sse/http"}

# Mount FastMCP SSE handlers
sse_app = mcp.sse_app()
app.mount("/mcp", sse_app)
app.mount("/sse", sse_app)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[Nexus MCP] Running HTTP/SSE Application on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

