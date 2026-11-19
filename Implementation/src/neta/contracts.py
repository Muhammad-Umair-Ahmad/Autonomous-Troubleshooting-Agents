from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field

BoundedText = Annotated[str, Field(min_length=1,max_length=160)]

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Fault(Strict):
    family: Literal['link_down', 'route_missing', 'route_wrong', 'address_missing', 'firewall_drop']
    device: Literal['pc1', 'r1', 'r2', 'pc2']
    target: str = Field(min_length=1, max_length=60)
    def identity(self):
        return f'{self.family}|{self.device}|{self.target}'

class Observation(Strict):
    evidence_id: str
    timestamp_utc: str
    device: str
    kind: str
    raw: dict
    parsed: object = None
    origin: Literal['measured', 'injected_telemetry'] = 'measured'

class ToolRequest(Strict):
    device: Literal['pc1', 'r1', 'r2', 'pc2']
    kind: Literal['interfaces', 'addresses', 'routes', 'firewall', 'ping']
    target: Literal['10.0.1.10', '10.0.2.10', '10.0.1.1', '10.0.2.1', '10.0.12.1', '10.0.12.2'] | None = None

class Finding(Strict):
    fault: Fault
    evidence_ids: list[str] = Field(min_length=1,max_length=2)
    explanation: str = Field(max_length=180)

class Diagnosis(Strict):
    healthy: bool
    findings: list[Finding] = Field(max_length=6)
    unresolved: list[BoundedText] = Field(default_factory=list,max_length=6)
    summary: str = Field(default='',max_length=240)

class RoleDecision(Strict):
    role: Literal['Orchestrator', 'Diagnostic', 'Knowledge', 'Remediation', 'Oversight']
    decision: str
    evidence_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

class Action(Strict):
    op: Literal['link_up', 'link_down', 'route_replace', 'route_delete', 'address_add', 'address_delete', 'firewall_clear', 'firewall_restore']
    device: Literal['pc1', 'r1', 'r2', 'pc2']
    target: str = Field(max_length=60)
    value: str = ''

class RepairPlan(Strict):
    actions: list[Action] = Field(max_length=6)
    preconditions: list[BoundedText] = Field(min_length=1,max_length=4)
    expected_effects: list[BoundedText] = Field(min_length=1,max_length=4)
    verification: list[BoundedText] = Field(min_length=1,max_length=6)
    rollback: Literal['restore_captured_state'] = 'restore_captured_state'
    evidence_ids: list[str] = Field(min_length=1,max_length=6)

class Review(Strict):
    reason: str = Field(max_length=280)
    evidence_ids: list[str] = Field(default_factory=list,max_length=6)
    approved: bool

class Scan(Strict):
    checks: list[ToolRequest] = Field(max_length=2)
