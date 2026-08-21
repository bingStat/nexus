from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DeviceId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="Exact Nexus device name; aliases and broadcast targets are not accepted.",
    ),
]
WorkspaceId = Annotated[str, Field(min_length=1, max_length=256)]
JobId = Annotated[str, Field(min_length=1, max_length=256)]
Command = Annotated[str, Field(min_length=1, max_length=262_144)]
Patch = Annotated[str, Field(min_length=1, max_length=2_000_000)]
Path = Annotated[str, Field(min_length=1, max_length=8_192)]
OptionalPath = Annotated[str, Field(max_length=8_192)]
BaseRef = Annotated[str, Field(max_length=1_024)]
StdinChars = Annotated[str, Field(max_length=262_144)]
TimeoutMs = Annotated[int, Field(ge=1_000, le=86_400_000)]
WaitSeconds = Annotated[int, Field(ge=0, le=120)]
YieldTimeMs = Annotated[int, Field(ge=0, le=300_000)]
MaxOutputTokens = Annotated[int, Field(ge=1, le=100_000)]
ReadOffset = Annotated[int, Field(ge=0)]
ReadLimit = Annotated[int, Field(ge=1, le=20_000)]
SessionId = Annotated[int, Field(ge=1)]

DeviceStatus = Literal["pending", "approved", "rejected", "revoked"]
WorkspaceMode = Literal["checkout", "worktree"]
BrokerRegion = Literal["eu", "cn"]
JobStatus = Literal["pending", "running", "completed", "failed", "timeout"]


class StrictInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenOutputModel(BaseModel):
    # Broker and runtime payloads may gain fields without breaking older clients.
    model_config = ConfigDict(extra="allow")


class BatchJobInput(StrictInputModel):
    device_id: DeviceId
    command: Command
    timeout_ms: TimeoutMs = 30_000
    wait_seconds: WaitSeconds | None = None


BatchJobs = Annotated[list[BatchJobInput], Field(min_length=1, max_length=16)]


class DeviceOutput(OpenOutputModel):
    device_id: str
    status: DeviceStatus


class DeviceListOutput(OpenOutputModel):
    devices: list[DeviceOutput]
    presence_errors: dict[str, str]


class BrokerHealthOutput(OpenOutputModel):
    status: str


class FleetCountsOutput(OpenOutputModel):
    online: int = Field(ge=0)
    degraded: int = Field(ge=0)
    offline: int = Field(ge=0)
    unknown: int = Field(ge=0)


class FleetStatusOutput(OpenOutputModel):
    brokers: dict[BrokerRegion, BrokerHealthOutput]
    counts: FleetCountsOutput
    devices: list[DeviceOutput]
    total: int = Field(ge=0)


class JobOutput(OpenOutputModel):
    id: str
    status: JobStatus
    target_device: str
    operation: str
    input: dict[str, Any]
    timeout_ms: int
    broker_region: BrokerRegion


class BatchFailureOutput(OpenOutputModel):
    status: Literal["failed"]
    error: str
    detail: str


class BatchOutput(OpenOutputModel):
    results: list[JobOutput | BatchFailureOutput]


class SelfTestOutput(OpenOutputModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    components: dict[str, dict[str, Any]]
