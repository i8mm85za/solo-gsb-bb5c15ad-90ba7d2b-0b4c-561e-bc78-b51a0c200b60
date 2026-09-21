"""端到端测试：展开与校验接口。

运行：pip install -r requirements.txt httpx && pytest
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def ms(**kw) -> dict:
    """构造一个小节，measure 自动填充。"""
    return kw


def req(flags: list[dict], **extra) -> dict:
    measures = [{"measure": i + 1, **f} for i, f in enumerate(flags)]
    return {"measures": measures, **extra}


# ---------------------------------------------------------------------------
# 基础展开
# ---------------------------------------------------------------------------


def test_plain_score():
    r = client.post("/api/v1/expand", json=req([ms(), ms(), ms()]))
    assert r.status_code == 200
    body = r.json()
    assert body["sequence"] == [1, 2, 3]
    assert [s["action"] for s in steps_of(body)] == ["continue", "continue", "end"]


def test_simple_paired_repeat():
    data = req(
        [
            ms(repeat_start=True),   # 1 |:
            ms(),                    # 2
            ms(repeat_end=True),     # 3 :|
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 1, 2, 3]
    actions = [s["action"] for s in steps_of(body)]
    assert actions[2] == "repeat_back"
    assert actions[-1] == "end"


def test_repeat_times_three():
    data = req(
        [
            ms(repeat_start=True),
            ms(repeat_end=True, repeat_times=3),
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 1, 2, 1, 2]


def test_implicit_start_repeat():
    # 曲首 :|：1..3 反复后继续
    data = req(
        [
            ms(),  # 1
            ms(),  # 2
            ms(repeat_end=True),  # 3
            ms(),  # 4
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 1, 2, 3, 4]


def steps_of(body):
    return body["steps"]


# ---------------------------------------------------------------------------
# 第一/第二结尾
# ---------------------------------------------------------------------------


def test_first_second_ending():
    data = req(
        [
            ms(repeat_start=True),                              # 1 |:
            ms(),                                               # 2
            ms(ending_start=True, ending_number=1, ending_stop=True,
               repeat_end=True),                                # 3 1. :|
            ms(ending_start=True, ending_number=2, ending_stop=True),  # 4 2.
            ms(),                                               # 5
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 1, 2, 4, 5]
    endings = [s["ending"] for s in steps_of(body)]
    assert endings == [None, None, 1, None, None, 2, None]


def test_implicit_close_final_ending():
    # 最后结尾后省略 :|
    data = req(
        [
            ms(repeat_start=True),                               # 1
            ms(ending_start=True, ending_number=1,
               ending_stop=True, repeat_end=True),               # 2 1. :|
            ms(ending_start=True, ending_number=2,
               ending_stop=True),                                # 3 2.
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 1, 3]


def test_three_endings():
    data = req(
        [
            ms(repeat_start=True, repeat_times=3),
            ms(ending_start=True, ending_number=1,
               ending_stop=True, repeat_end=True),
            ms(ending_start=True, ending_number=2,
               ending_stop=True, repeat_end=True),
            ms(ending_start=True, ending_number=3, ending_stop=True),
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 1, 3, 1, 4]


def test_nested_repeats():
    data = req(
        [
            ms(repeat_start=True),                      # 1 |: 外层
            ms(repeat_start=True),                      # 2 |: 内层
            ms(),                                       # 3
            ms(repeat_end=True),                        # 4 :|
            ms(repeat_end=True),                        # 5 :| 外层
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    # 内层 2,3 反复一次；外层整体再走一遍时内层不再反复
    assert body["sequence"] == [1, 2, 3, 4, 2, 3, 4, 5, 1, 2, 3, 4, 5]


def test_nested_with_inner_volta():
    data = req(
        [
            ms(repeat_start=True),                       # 1 |:
            ms(repeat_start=True),                       # 2  |:
            ms(),                                        # 3
            ms(ending_start=True, ending_number=1,
               ending_stop=True, repeat_end=True),       # 4 1. :|
            ms(ending_start=True, ending_number=2,
               ending_stop=True),                        # 5 2.
            ms(repeat_end=True),                         # 6 :|
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 4, 2, 3, 5, 6, 1, 2, 3, 5, 6]


# ---------------------------------------------------------------------------
# D.C. / D.S.
# ---------------------------------------------------------------------------


def test_dc_al_fine():
    data = req(
        [
            ms(),                          # 1
            ms(fine=True),                 # 2 Fine
            ms(),                          # 3
            ms(),                          # 4
            ms(navigation="dc_al_fine"),   # 5 D.C. al Fine
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 4, 5, 1, 2]
    assert steps_of(body)[-1]["action"] == "fine_end"


def test_ds_al_coda():
    data = req(
        [
            ms(),                             # 1
            ms(segno=True),                   # 2 Segno
            ms(),                             # 3
            ms(to_coda=True),                 # 4 To Coda
            ms(),                             # 5
            ms(navigation="ds_al_coda"),      # 6 D.S. al Coda
            ms(),                             # 7 不可达
            ms(coda=True),                    # 8 Coda
            ms(),                             # 9
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 4, 5, 6, 2, 3, 4, 8, 9]
    actions = [s["action"] for s in steps_of(body)]
    assert "navigation_jump" in actions
    assert "to_coda_jump" in actions
    # 第 7 小节不可达 -> 警告
    assert any(w["code"] == "UNREACHABLE_MEASURES" for w in body["warnings"])


def test_dc_plain_is_al_fine():
    data = req(
        [
            ms(fine=True),
            ms(),
            ms(navigation="dc"),
        ]
    )
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [1, 2, 3, 1]


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------


def test_unclosed_repeat():
    data = req([ms(repeat_start=True), ms()])
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail[0]["code"] == "UNCLOSED_REPEAT"
    assert detail[0]["measure"] == 1


def test_illegal_navigation_missing_segno():
    data = req([ms(), ms(navigation="ds_al_fine")])
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    codes = {d["code"] for d in r.json()["detail"]}
    assert "MISSING_SEGNO" in codes
    assert "MISSING_FINE" in codes


def test_coda_without_targets():
    data = req([ms(), ms(navigation="dc_al_coda")])
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    codes = {d["code"] for d in r.json()["detail"]}
    assert {"MISSING_TO_CODA", "MISSING_CODA"} <= codes


def test_navigation_inside_repeat_rejected():
    data = req(
        [
            ms(repeat_start=True),
            ms(fine=True),
            ms(navigation="dc_al_fine"),
            ms(repeat_end=True),
        ]
    )
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert any(d["code"] == "NAVIGATION_INSIDE_REPEAT" for d in r.json()["detail"])


def test_ending_times_mismatch():
    data = req(
        [
            ms(repeat_start=True, repeat_times=3),
            ms(ending_start=True, ending_number=1,
               ending_stop=True, repeat_end=True),
            ms(ending_start=True, ending_number=2, ending_stop=True),
        ]
    )
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert any(d["code"] == "REPEAT_TIMES_ENDING_MISMATCH" for d in r.json()["detail"])


def test_invalid_endings_number_sequence():
    data = req(
        [
            ms(repeat_start=True),
            ms(ending_start=True, ending_number=1,
               ending_stop=True, repeat_end=True),
            ms(ending_start=True, ending_number=3, ending_stop=True),
        ]
    )
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert any(d["code"] == "ENDING_NUMBER_SEQUENCE" for d in r.json()["detail"])


def test_error_response_has_no_partial_sequence():
    data = req([ms(repeat_start=True)])
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    body = r.json()
    assert "sequence" not in body
    assert "steps" not in body


def test_measure_numbers_must_increase():
    data = {
        "measures": [
            {"measure": 1},
            {"measure": 1},
        ]
    }
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert r.json()["detail"][0]["code"] == "MEASURE_NOT_INCREASING"


def test_max_steps_exceeded():
    data = req(
        [
            ms(repeat_start=True, repeat_times=99),
            ms(repeat_end=True),
        ],
        max_steps=10,
    )
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert r.json()["detail"][0]["code"] == "MAX_STEPS_EXCEEDED"
    assert "measure" in r.json()["detail"][0]


def test_server_cap_rejects_large_max_steps():
    data = req([ms()], max_steps=10_000_000)
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert r.json()["detail"][0]["code"] == "MAX_STEPS_TOO_LARGE"


def test_validation_endpoint_returns_all_issues():
    data = req(
        [
            ms(repeat_start=True),
            ms(ending_start=True),  # 缺 ending_number
        ]
    )
    r = client.post("/api/v1/validate", json=data)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "UNCLOSED_REPEAT" in codes
    assert "ENDING_NUMBER_MISSING" in codes
    assert body["repeat_sections"]


def test_validation_endpoint_valid():
    data = req([ms(), ms()])
    r = client.post("/api/v1/validate", json=data)
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_validation_endpoint_warns_unused_fine():
    data = req([ms(fine=True), ms()])
    body = client.post("/api/v1/validate", json=data).json()
    assert body["valid"] is True
    assert any(w["code"] == "UNUSED_FINE" for w in body["warnings"])


def test_multiple_navigation_rejected():
    data = req(
        [
            ms(fine=True),
            ms(navigation="dc_al_fine"),
            ms(navigation="dc_al_fine"),
        ]
    )
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert any(d["code"] == "MULTIPLE_NAVIGATION" for d in r.json()["detail"])


def test_marker_on_repeat_bar_rejected():
    data = req([ms(repeat_start=True, fine=True)])
    r = client.post("/api/v1/expand", json=data)
    assert r.status_code == 422
    assert any(d["code"] == "MARKER_ON_REPEAT_BAR" for d in r.json()["detail"])


def test_repeat_keeps_original_measure_numbers_with_gaps():
    # 原始小节号不连续（例如弱起 / 合并小节）时仍保留原号
    data = {
        "measures": [
            {"measure": 10, "repeat_start": True},
            {"measure": 12, "repeat_end": True},
        ]
    }
    body = client.post("/api/v1/expand", json=data).json()
    assert body["sequence"] == [10, 12, 10, 12]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}
