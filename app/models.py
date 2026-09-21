"""Request/response schemas for the expansion API."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Marker(str, Enum):
    repeat_begin = "repeat_begin"
    repeat_end = "repeat_end"
    ending_begin = "ending_begin"
    ending_end = "ending_end"
    segno = "segno"
    fine = "fine"
    to_coda = "to_coda"
    coda_sign = "coda_sign"
    dc_al_fine = "dc_al_fine"
    dc_al_coda = "dc_al_coda"
    ds_al_fine = "ds_al_fine"
    ds_al_coda = "ds_al_coda"


class Measure(BaseModel):
    """One notated measure with its structural markers."""

    number: int = Field(..., ge=1, description="Original measure number")
    markers: List[Marker] = Field(default_factory=list)
    ending_numbers: Optional[List[int]] = Field(
        default=None,
        description="Pass numbers of this ending, required with ending_begin, e.g. [1] or [1, 2]",
    )
    repeat_times: Optional[int] = Field(
        default=None, ge=1, le=64,
        description="Total play count of the repeat section, only on the repeat_end measure (default 2)",
    )


class ScoreRequest(BaseModel):
    title: Optional[str] = None
    measures: List[Measure] = Field(..., min_length=1)
    max_steps: Optional[int] = Field(
        default=None, ge=1,
        description="Per-request expansion step cap, bounded by the server limit",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "AABB with endings",
                    "measures": [
                        {"number": 1},
                        {"number": 2, "markers": ["repeat_begin"]},
                        {"number": 3},
                        {"number": 4, "markers": ["ending_begin"], "ending_numbers": [1]},
                        {"number": 5, "markers": ["ending_end", "repeat_end"]},
                        {"number": 6, "markers": ["ending_begin"], "ending_numbers": [2]},
                        {"number": 7, "markers": ["ending_end"]},
                        {"number": 8},
                    ],
                }
            ]
        }
    }


class IssueOut(BaseModel):
    code: str
    message: str
    measure: Optional[int] = None


class StepOut(BaseModel):
    step: int = Field(..., description="1-based position in the played sequence")
    measure: int = Field(..., description="Original measure number played at this step")
    action: Optional[str] = Field(
        default=None,
        description="Structural action fired at this step: repeat_back, dc_al_fine, "
                    "dc_al_coda, ds_al_fine, ds_al_coda, to_coda, fine_stop",
    )
    jump_to: Optional[int] = Field(default=None, description="Target measure of a jump action")


class ExpandResponse(BaseModel):
    title: Optional[str] = None
    measure_count: int
    total_steps: int
    max_steps: int
    steps: List[StepOut]
    warnings: List[IssueOut]


class ValidateResponse(BaseModel):
    valid: bool
    errors: List[IssueOut]
    warnings: List[IssueOut]
