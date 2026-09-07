"""ClaimRecord — the canonical, extracted shape of a claims-domain claim."""

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    code: str
    description: str
    units: int
    amount: float


class ClaimRecord(BaseModel):
    member_id: str = ""
    policy_no: str = ""
    provider_id: str | None = None
    provider_name: str | None = None
    network_status: str | None = None
    member_age: int | None = None
    service_start_date: str = ""
    service_end_date: str = ""
    diagnosis_codes: list[str] = Field(default_factory=list)
    procedure_codes: list[str] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    claimed_amount: float = 0.0
    currency: str = "INR"
