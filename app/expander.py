"""Core engine: score structure validation and repeat-path expansion.

This module is intentionally free of third-party dependencies so the
performance-semantics logic can be tested and reused on its own.

Supported notation markers (per measure):
    repeat_begin / repeat_end   paired repeats (repeat_end without an explicit
                                begin repeats from the start of the score)
    ending_begin / ending_end   first/second/... endings, the opening measure
                                carries ``ending_numbers`` (e.g. [1], [1, 2])
    segno / fine / to_coda / coda_sign
    dc_al_fine / dc_al_coda / ds_al_fine / ds_al_coda

Performance semantics implemented here:
  * a repeat section is played ``repeat_times`` times in total (default 2);
  * an ending bracket is played only when the current pass of the repeat
    section it belongs to is listed in its ``ending_numbers``;
  * a repeat_end written inside a non-first ending continues the same
    section (standard multi-ending notation such as 1./2. endings that each
    carry their own repeat barline);
  * D.C. jumps to the first measure, D.S. jumps to the segno;
  * after a D.C./D.S. jump, repeat barlines are ignored (played straight
    through), endings are still selected by their pass counters;
  * "al Fine" stops at the fine marker, "al Coda" jumps from to_coda to the
    coda sign and plays to the end of the score;
  * every jump instruction fires at most once, and the whole expansion is
    bounded by ``max_steps`` so malformed scores cannot loop forever.
"""
from __future__ import annotations

from dataclasses import dataclass, field

JUMP_MARKERS = frozenset({"dc_al_fine", "dc_al_coda", "ds_al_fine", "ds_al_coda"})
MAX_REPEAT_TIMES = 64
DEFAULT_MAX_STEPS = 1000


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MeasureData:
    """One notated measure and its structural markers."""

    number: int
    markers: frozenset
    ending_numbers: tuple | None = None
    repeat_times: int | None = None


@dataclass
class Issue:
    """A validation/expansion problem (or warning) located at a measure."""

    code: str
    message: str
    measure: int | None = None

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "measure": self.measure}


class ExpansionError(Exception):
    """Raised when a score cannot be expanded; carries all detected issues."""

    def __init__(self, issues: list):
        self.issues = list(issues)
        super().__init__(self.issues[0].message if self.issues else "expansion failed")


@dataclass
class Section:
    """A repeat section: measures [begin_idx, end_idx] played `times` times."""

    id: int
    begin_idx: int
    end_idx: int
    times: int = 2


@dataclass
class EndingBracket:
    """One volta bracket: measures [begin_idx, end_idx], played on `numbers` passes."""

    id: int
    begin_idx: int
    end_idx: int
    numbers: tuple
    group_id: int = 0
    section_id: int | None = None


@dataclass
class StepEvent:
    """One played measure in the expanded sequence."""

    step: int
    measure: int
    action: str | None = None
    jump_to: int | None = None


@dataclass
class Structure:
    """Fully analysed score: sections, endings, jumps, issues."""

    measures: list
    sections: list = field(default_factory=list)
    brackets: list = field(default_factory=list)
    repeat_end_to_section: dict = field(default_factory=dict)
    bracket_at_begin: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    segno_idx: int | None = None
    fine_idx: int | None = None
    to_coda_idx: int | None = None
    coda_idx: int | None = None
    jump_idx: int | None = None
    jump_kind: str | None = None
    jump_target_idx: int | None = None


# ---------------------------------------------------------------------------
# Structure analysis
# ---------------------------------------------------------------------------

def build_structure(measures: list) -> Structure:
    """Analyse the notated measures into a Structure.

    Never raises: all problems are collected into ``st.errors`` /
    ``st.warnings`` so callers can report every issue at once.
    """
    st = Structure(measures=measures)
    _check_measures(st)
    _match_endings(st)
    _match_repeats(st)
    _attach_endings(st)
    _analyse_jumps(st)
    _check_ending_coverage(st)
    return st


def _check_measures(st: Structure) -> None:
    seen: dict = {}
    for m in st.measures:
        if m.number in seen:
            st.errors.append(Issue(
                "DUPLICATE_MEASURE",
                f"measure number {m.number} is used more than once",
                m.number,
            ))
        else:
            seen[m.number] = True
    for m in st.measures:
        mk = m.markers
        if "ending_begin" in mk and not m.ending_numbers:
            st.errors.append(Issue(
                "ENDING_NUMBERS_MISSING",
                "ending_begin requires non-empty ending_numbers (e.g. [1])",
                m.number,
            ))
        if m.ending_numbers and "ending_begin" not in mk:
            st.warnings.append(Issue(
                "ENDING_NUMBERS_IGNORED",
                "ending_numbers is ignored without ending_begin",
                m.number,
            ))
        if m.repeat_times is not None and "repeat_end" not in mk:
            st.warnings.append(Issue(
                "REPEAT_TIMES_IGNORED",
                "repeat_times is ignored without repeat_end",
                m.number,
            ))
        if m.repeat_times is not None and not 1 <= m.repeat_times <= MAX_REPEAT_TIMES:
            st.errors.append(Issue(
                "INVALID_REPEAT_TIMES",
                f"repeat_times must be between 1 and {MAX_REPEAT_TIMES}",
                m.number,
            ))


def _match_endings(st: Structure) -> None:
    """Pair ending_begin/ending_end into brackets and group adjacent brackets."""
    open_idx = None
    open_numbers = None
    for i, m in enumerate(st.measures):
        has_begin = "ending_begin" in m.markers
        has_end = "ending_end" in m.markers
        if has_begin and has_end and open_idx is None:
            # one-measure ending bracket
            st.brackets.append(EndingBracket(
                len(st.brackets), i, i, tuple(m.ending_numbers or ())))
            continue
        if has_end:
            if open_idx is None:
                st.errors.append(Issue(
                    "ENDING_END_WITHOUT_BEGIN",
                    "ending_end without a preceding ending_begin",
                    m.number,
                ))
            else:
                st.brackets.append(EndingBracket(
                    len(st.brackets), open_idx, i, tuple(open_numbers or ())))
                open_idx = None
                open_numbers = None
        if has_begin:
            if open_idx is not None:
                st.errors.append(Issue(
                    "NESTED_ENDING",
                    "ending_begin while another ending is still open",
                    m.number,
                ))
            else:
                open_idx = i
                open_numbers = m.ending_numbers
    if open_idx is not None:
        st.errors.append(Issue(
            "UNCLOSED_ENDING",
            "ending_begin is never closed by ending_end",
            st.measures[open_idx].number,
        ))

    # group adjacent brackets (a 1st/2nd ending pair forms one group)
    prev_end = None
    group_id = -1
    for b in st.brackets:
        if prev_end is None or b.begin_idx > prev_end + 1:
            group_id += 1
        b.group_id = group_id
        prev_end = b.end_idx if prev_end is None else max(prev_end, b.end_idx)


def _match_repeats(st: Structure) -> None:
    """Pair repeat_begin/repeat_end into sections.

    A repeat_end inside a non-first ending of a group continues the section
    started by the group's first ending (standard multi-ending notation).
    A repeat_end without an open begin repeats implicitly from the start.
    """
    group_first: dict = {}
    for b in st.brackets:
        group_first.setdefault(b.group_id, b)

    def bracket_at(idx: int):
        for b in st.brackets:
            if b.begin_idx <= idx <= b.end_idx:
                return b
        return None

    stack: list = []
    for i, m in enumerate(st.measures):
        if "repeat_begin" in m.markers:
            stack.append(i)
        if "repeat_end" not in m.markers:
            continue

        continued = False
        bracket = bracket_at(i)
        if bracket is not None and group_first[bracket.group_id] is not bracket:
            first = group_first[bracket.group_id]
            for j in range(first.begin_idx, first.end_idx + 1):
                sec_id = st.repeat_end_to_section.get(j)
                if sec_id is not None:
                    sec = st.sections[sec_id]
                    sec.end_idx = i
                    if m.repeat_times is not None:
                        sec.times = m.repeat_times
                    st.repeat_end_to_section[i] = sec_id
                    continued = True
                    break
        if continued:
            continue

        if stack:
            begin = stack.pop()
        else:
            begin = 0
            st.warnings.append(Issue(
                "IMPLICIT_REPEAT_FROM_START",
                "repeat_end without repeat_begin: repeating from the start",
                m.number,
            ))
        sec = Section(
            id=len(st.sections),
            begin_idx=begin,
            end_idx=i,
            times=m.repeat_times if m.repeat_times is not None else 2,
        )
        st.sections.append(sec)
        st.repeat_end_to_section[i] = sec.id

    for begin in stack:
        st.errors.append(Issue(
            "UNCLOSED_REPEAT",
            "repeat_begin is never closed by repeat_end",
            st.measures[begin].number,
        ))


def _attach_endings(st: Structure) -> None:
    """Attach every ending bracket to the repeat section it belongs to."""
    for b in st.brackets:
        containing = [s for s in st.sections if s.begin_idx <= b.begin_idx <= s.end_idx]
        if containing:
            sec = min(containing, key=lambda s: (s.end_idx - s.begin_idx, -s.begin_idx))
            b.section_id = sec.id
            continue
        preceding = [s for s in st.sections if s.end_idx < b.begin_idx]
        if preceding:
            b.section_id = max(preceding, key=lambda s: s.end_idx).id
            continue
        st.errors.append(Issue(
            "ENDING_WITHOUT_REPEAT",
            "ending is not attached to any repeat section",
            st.measures[b.begin_idx].number,
        ))
    st.bracket_at_begin = {b.begin_idx: b.id for b in st.brackets if b.section_id is not None}


def _analyse_jumps(st: Structure) -> None:
    def find_all(marker: str) -> list:
        return [i for i, m in enumerate(st.measures) if marker in m.markers]

    segnos = find_all("segno")
    fines = find_all("fine")
    tocodas = find_all("to_coda")
    codas = find_all("coda_sign")
    jumps = sorted(
        (i, marker)
        for i, m in enumerate(st.measures)
        for marker in JUMP_MARKERS
        if marker in m.markers
    )

    for label, lst in (("segno", segnos), ("fine", fines),
                       ("to_coda", tocodas), ("coda_sign", codas)):
        for idx in lst[1:]:
            st.errors.append(Issue(
                "DUPLICATE_MARKER",
                f"multiple '{label}' markers are not allowed",
                st.measures[idx].number,
            ))

    if len(jumps) > 1:
        st.errors.append(Issue(
            "MULTIPLE_JUMPS",
            "only one D.C./D.S. instruction is allowed per score",
            st.measures[jumps[1][0]].number,
        ))

    st.segno_idx = segnos[0] if segnos else None
    st.fine_idx = fines[0] if fines else None
    st.to_coda_idx = tocodas[0] if tocodas else None
    st.coda_idx = codas[0] if codas else None

    if len(jumps) == 1:
        jidx, kind = jumps[0]
        st.jump_idx = jidx
        st.jump_kind = kind
        if kind.startswith("ds"):
            if st.segno_idx is None:
                st.errors.append(Issue(
                    "DS_WITHOUT_SEGNO",
                    "D.S. instruction but no segno marker in the score",
                    st.measures[jidx].number,
                ))
            else:
                if st.segno_idx >= jidx:
                    st.errors.append(Issue(
                        "ILLEGAL_JUMP",
                        "segno must appear before the D.S. instruction",
                        st.measures[jidx].number,
                    ))
                st.jump_target_idx = st.segno_idx
        else:
            st.jump_target_idx = 0
        if kind.endswith("al_fine"):
            if st.fine_idx is None:
                st.errors.append(Issue(
                    "MISSING_FINE",
                    f"{kind} requires a fine marker",
                    st.measures[jidx].number,
                ))
            elif st.jump_target_idx is not None and st.fine_idx < st.jump_target_idx:
                st.errors.append(Issue(
                    "ILLEGAL_JUMP",
                    "fine is not reachable after the jump",
                    st.measures[st.fine_idx].number,
                ))
        else:  # al Coda
            if st.to_coda_idx is None:
                st.errors.append(Issue(
                    "MISSING_TO_CODA",
                    f"{kind} requires a to_coda marker",
                    st.measures[jidx].number,
                ))
            if st.coda_idx is None:
                st.errors.append(Issue(
                    "MISSING_CODA_SIGN",
                    f"{kind} requires a coda_sign marker",
                    st.measures[jidx].number,
                ))
            if (st.to_coda_idx is not None and st.jump_target_idx is not None
                    and st.to_coda_idx < st.jump_target_idx):
                st.errors.append(Issue(
                    "ILLEGAL_JUMP",
                    "to_coda is not reachable after the jump",
                    st.measures[st.to_coda_idx].number,
                ))
            if (st.to_coda_idx is not None and st.coda_idx is not None
                    and st.coda_idx <= st.to_coda_idx):
                st.errors.append(Issue(
                    "ILLEGAL_JUMP",
                    "coda_sign must appear after to_coda",
                    st.measures[st.coda_idx].number,
                ))

    # notation present but never used
    if st.jump_kind is None or not st.jump_kind.endswith("al_fine"):
        for idx in fines[:1]:
            st.warnings.append(Issue(
                "UNUSED_FINE", "fine marker is never used", st.measures[idx].number))
    if st.jump_kind is None or not st.jump_kind.endswith("al_coda"):
        for idx in tocodas[:1]:
            st.warnings.append(Issue(
                "UNUSED_TO_CODA", "to_coda marker is never used", st.measures[idx].number))
        for idx in codas[:1]:
            st.warnings.append(Issue(
                "UNUSED_CODA_SIGN", "coda_sign marker is never used", st.measures[idx].number))
    if st.jump_kind is None or not st.jump_kind.startswith("ds"):
        for idx in segnos[:1]:
            st.warnings.append(Issue(
                "UNUSED_SEGNO", "segno marker is never used", st.measures[idx].number))


def _check_ending_coverage(st: Structure) -> None:
    for sec in st.sections:
        nums = set()
        for b in st.brackets:
            if b.section_id == sec.id:
                nums.update(b.numbers)
        if not nums:
            continue
        for p in range(1, sec.times + 1):
            if p not in nums:
                st.warnings.append(Issue(
                    "NO_ENDING_FOR_PASS",
                    f"no ending defined for pass {p} of the repeat",
                    st.measures[sec.begin_idx].number,
                ))
        for b in st.brackets:
            if b.section_id != sec.id:
                continue
            for x in b.numbers:
                if x > sec.times:
                    st.warnings.append(Issue(
                        "ENDING_NEVER_PLAYED",
                        f"ending {x} exceeds the repeat count ({sec.times})",
                        st.measures[b.begin_idx].number,
                    ))


# ---------------------------------------------------------------------------
# Expansion (playback simulation)
# ---------------------------------------------------------------------------

def expand_structure(st: Structure, max_steps: int = DEFAULT_MAX_STEPS) -> list:
    """Simulate performance and return the played measures as StepEvents.

    Raises ExpansionError if the expansion exceeds ``max_steps``; no partial
    sequence is returned in that case.
    """
    measures = st.measures
    n = len(measures)
    jumpbacks = [0] * len(st.sections)  # completed back-jumps per section
    steps: list = []
    pc = 0
    post_jump = False   # True after a D.C./D.S. has been taken
    jump_fired = False
    coda_taken = False

    while 0 <= pc < n:
        if len(steps) >= max_steps:
            raise ExpansionError([Issue(
                "MAX_STEPS_EXCEEDED",
                f"expansion exceeded the limit of {max_steps} steps",
                measures[pc].number,
            )])
        m = measures[pc]

        # ending bracket: play it only on the passes listed in ending_numbers
        bracket_id = st.bracket_at_begin.get(pc)
        if bracket_id is not None:
            b = st.brackets[bracket_id]
            sec = st.sections[b.section_id]
            if (1 + jumpbacks[sec.id]) not in b.numbers:
                pc = b.end_idx + 1
                continue

        steps.append(StepEvent(step=len(steps) + 1, measure=m.number))
        step = steps[-1]
        mk = m.markers

        # al Fine: stop at the fine marker on the post-jump pass
        if (post_jump and st.jump_kind in ("dc_al_fine", "ds_al_fine")
                and "fine" in mk):
            step.action = "fine_stop"
            break

        # al Coda: at to_coda, jump to the coda sign
        if (post_jump and st.jump_kind in ("dc_al_coda", "ds_al_coda")
                and "to_coda" in mk and not coda_taken):
            coda_taken = True
            step.action = "to_coda"
            step.jump_to = measures[st.coda_idx].number
            pc = st.coda_idx
            continue

        # repeat barline (ignored after a D.C./D.S. jump)
        if "repeat_end" in mk and not post_jump:
            sec_id = st.repeat_end_to_section.get(pc)
            if sec_id is not None:
                sec = st.sections[sec_id]
                if 1 + jumpbacks[sec_id] < sec.times:
                    jumpbacks[sec_id] += 1
                    # nested sections restart when the enclosing section repeats
                    for t in st.sections:
                        if (t.id != sec_id and sec.begin_idx <= t.begin_idx
                                and t.end_idx <= sec.end_idx):
                            jumpbacks[t.id] = 0
                    step.action = "repeat_back"
                    step.jump_to = measures[sec.begin_idx].number
                    pc = sec.begin_idx
                    continue

        # D.C./D.S. instruction (fires once)
        if not jump_fired and any(marker in mk for marker in JUMP_MARKERS):
            jump_fired = True
            post_jump = True
            step.action = st.jump_kind
            step.jump_to = measures[st.jump_target_idx].number
            pc = st.jump_target_idx
            continue

        pc += 1

    return steps


def expand(measures: list, max_steps: int = DEFAULT_MAX_STEPS) -> tuple:
    """Validate and expand a score.

    Returns (steps, warnings). Raises ExpansionError with every detected
    issue when the structure is invalid or the step limit is exceeded;
    no partial sequence is produced on error.
    """
    st = build_structure(measures)
    if st.errors:
        raise ExpansionError(st.errors)
    steps = expand_structure(st, max_steps)
    return steps, st.warnings


def validate(measures: list, max_steps: int = DEFAULT_MAX_STEPS) -> tuple:
    """Validate a score without producing a sequence.

    Returns (errors, warnings). A structurally valid score is additionally
    test-expanded so step-limit problems are reported here as well.
    """
    st = build_structure(measures)
    errors = list(st.errors)
    if not errors:
        try:
            expand_structure(st, max_steps)
        except ExpansionError as exc:
            errors.extend(exc.issues)
    return errors, st.warnings
