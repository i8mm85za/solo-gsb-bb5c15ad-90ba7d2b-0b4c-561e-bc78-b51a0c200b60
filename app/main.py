"""FastAPI 入口：展开与结构校验接口。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .analyzer import analyze
from .config import get_settings
from .errors import StructuralError
from .expander import ExpansionError, expand
from .models import (
    ExpandRequest,
    ExpandResponse,
    Issue,
    Step,
    ValidateResponse,
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "提交按小节排列的结构标记（成对反复、第一/第二结尾、"
        "D.C./D.S. al Coda/Fine），返回按演奏语义展开的实际小节序列。"
    ),
)


def _issue(err: StructuralError) -> Issue:
    return Issue(code=err.code, message=err.message, measure=err.measure)


def _check_measure_numbers(measures) -> list[StructuralError]:
    """小节号必须严格递增（Pydantic 只保证正整数，不保证顺序）。"""
    errors: list[StructuralError] = []
    for prev, cur in zip(measures, measures[1:]):
        if cur.measure <= prev.measure:
            errors.append(
                StructuralError(
                    "MEASURE_NOT_INCREASING",
                    f"小节号必须严格递增：第 {cur.measure} 小节出现在第 {prev.measure} 小节之后",
                    cur.measure,
                )
            )
    return errors


def _sections_payload(analysis) -> list[dict]:
    out = []
    for sec in analysis.sections:
        out.append(
            {
                "start_measure": analysis.mnum(sec.start),
                "end_measure": analysis.mnum(sec.close_end),
                "times": sec.times,
                "endings": [
                    {
                        "number": g.number,
                        "start_measure": analysis.mnum(g.start),
                        "end_measure": analysis.mnum(g.end),
                    }
                    for g in sorted(sec.endings.values(), key=lambda g: g.number)
                ],
                "implicit_start": sec.start_marker is None,
                "implicit_close": sec.implicit_close,
            }
        )
    return out


@app.exception_handler(ExpansionError)
async def expansion_error_handler(request: Request, exc: ExpansionError) -> JSONResponse:
    # 展开期错误同样带小节定位，且不返回任何部分序列
    issue = Issue(code=exc.code, message=exc.message, measure=exc.measure)
    return JSONResponse(status_code=422, content={"detail": [issue.model_dump(exclude_none=True)]})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/validate", response_model=ValidateResponse)
def validate(req: ExpandRequest) -> ValidateResponse:
    """只做结构校验，不展开；无论是否合法都返回 200 与全部问题。"""
    number_errors = _check_measure_numbers(req.measures)
    analysis = analyze(req.measures)
    errors = number_errors + analysis.errors
    return ValidateResponse(
        valid=not errors,
        errors=[_issue(e).model_dump(exclude_none=True) for e in errors],  # type: ignore[list-item]
        warnings=[_issue(w).model_dump(exclude_none=True) for w in analysis.warnings],  # type: ignore[list-item]
        repeat_sections=_sections_payload(analysis),
    )


@app.post("/api/v1/expand", response_model=ExpandResponse)
def do_expand(req: ExpandRequest) -> ExpandResponse:
    """按演奏语义展开；结构非法或超步数时返回 422，不产出部分序列。"""
    number_errors = _check_measure_numbers(req.measures)
    if number_errors:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={
                "detail": [
                    Issue(
                        code=e.code, message=e.message, measure=e.measure
                    ).model_dump(exclude_none=True)
                    for e in number_errors
                ]
            },
        )

    max_steps = req.max_steps or settings.default_max_steps
    if max_steps > settings.max_expansion_steps:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={
                "detail": [
                    Issue(
                        code="MAX_STEPS_TOO_LARGE",
                        message=(
                            f"请求的 max_steps={max_steps} 超过服务端上限 "
                            f"{settings.max_expansion_steps}（MAX_EXPANSION_STEPS）"
                        ),
                    ).model_dump(exclude_none=True)
                ]
            },
        )

    analysis = analyze(req.measures)
    if analysis.errors:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={
                "detail": [
                    Issue(
                        code=e.code, message=e.message, measure=e.measure
                    ).model_dump(exclude_none=True)
                    for e in analysis.errors
                ]
            },
        )

    played = expand(analysis, max_steps=max_steps)
    return ExpandResponse(
        sequence=[s.measure for s in played],
        steps=[
            Step(index=i + 1, measure=s.measure, ending=s.ending, action=s.action)
            for i, s in enumerate(played)
        ],
        total_steps=len(played),
        warnings=[_issue(w).model_dump(exclude_none=True) for w in analysis.warnings],  # type: ignore[list-item]
    )
