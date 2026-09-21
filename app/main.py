"""FastAPI application exposing score expansion and structure validation."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config
from .expander import ExpansionError, MeasureData, build_structure, expand_structure
from .models import (
    ExpandResponse,
    IssueOut,
    ScoreRequest,
    StepOut,
    ValidateResponse,
)

app = FastAPI(
    title="Score Repeat Path Expansion API",
    version="1.0.0",
    description=(
        "Expands the repeat structure of a score (paired repeats, first/second "
        "endings, D.C./D.S. al Coda/Fine) into the actually played measure "
        "sequence, keeping the original measure number of every step."
    ),
)


@app.exception_handler(ExpansionError)
async def expansion_error_handler(_: Request, exc: ExpansionError) -> JSONResponse:
    # structural/expansion failure: report every located issue, no partial sequence
    return JSONResponse(
        status_code=422,
        content={"errors": [issue.as_dict() for issue in exc.issues]},
    )


def _to_measure_data(req: ScoreRequest) -> list:
    return [
        MeasureData(
            number=m.number,
            markers=frozenset(marker.value for marker in m.markers),
            ending_numbers=tuple(m.ending_numbers) if m.ending_numbers else None,
            repeat_times=m.repeat_times,
        )
        for m in req.measures
    ]


def _effective_limit(req: ScoreRequest) -> int:
    if req.max_steps is None:
        return config.MAX_EXPAND_STEPS
    return min(req.max_steps, config.MAX_EXPAND_STEPS)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "score-repeat-expansion",
        "docs": "/docs",
        "endpoints": {
            "expand": "POST /expand",
            "validate": "POST /validate",
            "health": "GET /health",
        },
        "max_expand_steps": config.MAX_EXPAND_STEPS,
    }


@app.post("/expand", response_model=ExpandResponse, tags=["score"])
def expand_score(req: ScoreRequest) -> ExpandResponse:
    """Expand a score into the played measure sequence.

    Returns 422 with measure-located errors (and no partial sequence) on
    unclosed repeats, illegal jumps or when the step limit is exceeded.
    """
    measures = _to_measure_data(req)
    limit = _effective_limit(req)
    st = build_structure(measures)
    if st.errors:
        raise ExpansionError(st.errors)
    steps = expand_structure(st, limit)
    return ExpandResponse(
        title=req.title,
        measure_count=len(measures),
        total_steps=len(steps),
        max_steps=limit,
        steps=[
            StepOut(step=s.step, measure=s.measure, action=s.action, jump_to=s.jump_to)
            for s in steps
        ],
        warnings=[IssueOut(**w.as_dict()) for w in st.warnings],
    )


@app.post("/validate", response_model=ValidateResponse, tags=["score"])
def validate_score(req: ScoreRequest) -> ValidateResponse:
    """Validate the score structure without producing a sequence."""
    measures = _to_measure_data(req)
    limit = _effective_limit(req)
    st = build_structure(measures)
    errors = list(st.errors)
    if not errors:
        try:
            expand_structure(st, limit)
        except ExpansionError as exc:
            errors.extend(exc.issues)
    return ValidateResponse(
        valid=not errors,
        errors=[IssueOut(**e.as_dict()) for e in errors],
        warnings=[IssueOut(**w.as_dict()) for w in st.warnings],
    )
