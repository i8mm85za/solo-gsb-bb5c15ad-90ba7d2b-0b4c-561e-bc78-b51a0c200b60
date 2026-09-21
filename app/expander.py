"""展开虚拟机：按演奏语义生成实际小节序列。

状态模型
--------
* 每个反复段在每一个“演奏纪元”（epoch）中维护一个当前遍数计数器：
  epoch 0 = 从头至 D.C./D.S. 指令的首遍演奏；epoch 1 = 折返回去后的第二遍。
* 首遍中，计数器在首次进入反复段时置 1；段内的 :| 使遍数 +1 并跳回段首，
  到达声明遍数后继续向后。嵌套反复在外层第二遍中已经“完成”，
  因而内层不再反复（与常见制谱软件的展开约定一致）。
* 结尾（房子）小节只在“结尾号 == 所属反复段当前遍数”时演奏，其余跳过。
* 按标准演奏惯例，D.C./D.S. 折返后不再重复此前已奏过的反复段：
  新纪元中首次触及反复段时直接视为最后一遍（:| 不再跳回，只走最后结尾）。
* Fine / To Coda 只在折返后的第二遍生效；D.C./D.S. 指令只触发一次。
"""

from __future__ import annotations

from dataclasses import dataclass

from .analyzer import Analysis, Navigation, Section


class ExpansionError(Exception):
    """运行期错误（非法跳转 / 超过最大步数）。"""

    def __init__(self, code: str, message: str, measure: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.measure = measure


@dataclass
class PlayedStep:
    measure: int
    ending: int | None
    action: str


def expand(analysis: Analysis, max_steps: int) -> list[PlayedStep]:
    """执行展开。分析阶段存在错误时不应调用本函数。"""
    n = len(analysis.measures)
    measures = analysis.measures

    # 结尾小节 -> 所属反复段
    ending_owner: dict[int, Section] = {}
    for sec in analysis.sections:
        for g in sec.endings.values():
            for pos in range(g.start, g.end + 1):
                ending_owner[pos] = sec

    # (sid, epoch) -> 当前遍数
    state: dict[tuple[int, int], int] = {}

    def current_pass(sec: Section, epoch: int) -> int:
        key = (sec.sid, epoch)
        if key not in state:
            # 折返后的纪元：已奏过的反复段不再重复，直接视为最后一遍
            state[key] = sec.times if epoch > 0 else 1
        return state[key]

    def sections_at(pos: int) -> list[Section]:
        return [s for s in analysis.sections if s.start <= pos <= s.close_end]

    steps: list[PlayedStep] = []

    epoch = 0
    pos = 0

    def add_step(ending: int | None, action: str) -> None:
        steps.append(PlayedStep(measure=measures[pos].measure, ending=ending, action=action))

    while pos < n:
        if len(steps) >= max_steps:
            raise ExpansionError(
                "MAX_STEPS_EXCEEDED",
                f"展开超过最大步数 {max_steps}，请检查是否存在异常反复或循环",
                measures[pos].measure,
            )

        m = measures[pos]
        nav: Navigation | None = analysis.navigation

        # ---- 结尾（房子）过滤：只演奏与当前遍数匹配的结尾 ----
        ending_no: int | None = None
        if pos in ending_owner:
            owner = ending_owner[pos]
            ending_no = analysis.ending_at[pos]
            if ending_no != current_pass(owner, epoch):
                pos += 1
                continue

        # 首次进入包含本小节的反复段（含 D.S./D.C. 从段中进入的情况）
        for sec in sections_at(pos):
            current_pass(sec, epoch)

        action = "continue"
        next_pos = pos + 1
        terminate = False

        # ---- 右反复记号 :| ----
        if m.repeat_end:
            sec = analysis.end_owner.get(pos)
            if sec is None:  # 理论上不会发生：分析阶段已报错
                raise ExpansionError(
                    "INVALID_REPEAT_END",
                    "右反复记号 :| 找不到所属反复段",
                    m.measure,
                )
            passed = current_pass(sec, epoch)
            if passed < sec.times:
                state[(sec.sid, epoch)] = passed + 1
                action = "repeat_back"
                next_pos = sec.start
            else:
                action = "repeat_finish"

        # ---- Fine：仅折返后生效 ----
        elif m.fine and epoch > 0 and nav and nav.fine == pos:
            action = "fine_end"
            terminate = True

        # ---- To Coda：仅折返后生效 ----
        elif m.to_coda and epoch > 0 and nav and nav.to_coda == pos:
            if nav.coda is None:
                raise ExpansionError(
                    "INVALID_CODA_JUMP",
                    "To Coda 找不到 Coda 目标",
                    m.measure,
                )
            action = "to_coda_jump"
            next_pos = nav.coda

        # ---- D.C. / D.S.：只在首遍触发一次 ----
        elif nav is not None and nav.position == pos and epoch == 0:
            epoch = 1
            if nav.kind.startswith("ds"):
                if nav.segno is None:
                    raise ExpansionError(
                        "INVALID_NAVIGATION_TARGET",
                        "D.S. 缺少 Segno 目标",
                        m.measure,
                    )
                next_pos = nav.segno
            else:
                next_pos = 0
            action = "navigation_jump"

        add_step(ending_no if ending_owner.get(pos) else None, action)
        pos = next_pos

        if terminate:
            break

        # 防御：折返后若仍走到导航指令处（没有 Fine/To Coda 兜底），直接结束
        if (
            epoch > 0
            and nav is not None
            and pos == nav.position
            and nav.fine is None
            and nav.to_coda is None
        ):
            steps[-1] = PlayedStep(
                measure=steps[-1].measure, ending=steps[-1].ending, action="end"
            )
            break

    # 自然走到曲尾时，把最后一步标为 end；Fine 终止（fine_end）等语义动作保留
    if steps and steps[-1].action in ("continue", "repeat_finish"):
        steps[-1] = PlayedStep(
            measure=steps[-1].measure, ending=steps[-1].ending, action="end"
        )
    return steps
