# 乐谱反复路径展开 API

使用 Python + FastAPI 实现的乐谱反复路径展开服务。提交**按小节排列的结构标记**，
服务按演奏语义生成**实际演奏的小节序列**，并为每一步保留**原始小节号**。

支持的结构：

- 成对反复 `|: … :|`（含曲首隐式反复、嵌套反复、`repeat_times` 多遍反复）；
- 第一/第二（及第三……）结尾（volta 房子），结尾数须与反复遍数一致；
- `D.C.` / `D.S.` `al Fine` 与 `al Coda`（含 Segno / Fine / To Coda / Coda）。

遇到**未闭合反复、非法跳转、超过最大展开步数**等问题时，返回带**小节定位**的
422 错误，且**不产出任何部分序列**。

## 一条命令启动

需要 Docker（含 Compose 插件）：

```bash
docker compose up --build
```

启动完成后访问：

- 服务地址与端口：<http://localhost:8000>
- 健康检查：<http://localhost:8000/health>
- 交互式 API 文档（Swagger UI）：<http://localhost:8000/docs>
- OpenAPI Schema：<http://localhost:8000/openapi.json>

本地无 Docker 时也可直接运行：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 必要配置

全部通过环境变量配置，均有默认值（见 `docker-compose.yml`）：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_EXPANSION_STEPS` | `100000` | 服务端允许的最大展开步数硬上限；请求超过此值直接 422 |
| `DEFAULT_MAX_STEPS` | `10000` | 请求未指定 `max_steps` 时使用的默认值（不得大于硬上限） |
| 端口 | `8000` | 容器固定监听 8000；如需改宿主机端口，修改 compose 的端口映射，如 `"9000:8000"` |

## 接口

### `POST /api/v1/expand` — 展开

请求体：

```json
{
  "max_steps": 10000,
  "measures": [
    {"measure": 1, "repeat_start": true},
    {"measure": 2},
    {"measure": 3, "ending_start": true, "ending_number": 1, "ending_stop": true, "repeat_end": true},
    {"measure": 4, "ending_start": true, "ending_number": 2, "ending_stop": true},
    {"measure": 5}
  ]
}
```

`measure` 为原始小节号（正整数、严格递增，可以不连续，如弱起/合并小节）。
标记字段（除 `measure` 外均可省略，默认 `false`/`null`）：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `repeat_start` | bool | 左反复记号 `|:` |
| `repeat_end` | bool | 右反复记号 `:|` |
| `repeat_times` | int ≥2 | 反复段演奏遍数，写在 `|:` 或 `:|` 小节上，默认 2；有结尾时必须等于结尾数 |
| `ending_start` | bool | 结尾（房子）起始小节 |
| `ending_number` | int | 结尾序号：1 = 第一结尾，2 = 第二结尾…… |
| `ending_stop` | bool | 结尾结束小节；省略时以下一个结尾起始为界 |
| `segno` | bool | Segno 𝄋（D.S. 目标） |
| `coda` | bool | Coda 𝄌 目标 |
| `fine` | bool | Fine |
| `to_coda` | bool | To Coda |
| `navigation` | string | `dc` / `ds` / `dc_al_coda` / `ds_al_coda` / `dc_al_fine` / `ds_al_fine`（裸 `dc`/`ds` 语义同 al Fine） |

响应（上例：`1,2,3` 反复后走第二结尾）：

```json
{
  "sequence": [1, 2, 3, 1, 2, 4, 5],
  "steps": [
    {"index": 1, "measure": 1, "ending": null, "action": "continue"},
    {"index": 2, "measure": 2, "ending": null, "action": "continue"},
    {"index": 3, "measure": 3, "ending": 1, "action": "repeat_back"},
    {"index": 4, "measure": 1, "ending": null, "action": "continue"},
    {"index": 5, "measure": 2, "ending": null, "action": "continue"},
    {"index": 6, "measure": 4, "ending": 2, "action": "continue"},
    {"index": 7, "measure": 5, "ending": null, "action": "end"}
  ],
  "total_steps": 7,
  "warnings": []
}
```

`action` 取值：`continue`（继续）、`repeat_back`（`:|` 跳回段首）、
`repeat_finish`（反复段奏完）、`navigation_jump`（触发 D.C./D.S.）、
`to_coda_jump`（跳往 Coda）、`fine_end`（在 Fine 处结束）、`end`（全曲最后一步）。

错误响应（HTTP 422，`detail` 中每条错误都带 `code`、`message` 与可选的 `measure`）：

```json
{
  "detail": [
    {"code": "UNCLOSED_REPEAT", "message": "存在未闭合的左反复记号 |:（缺少配对的 :|）", "measure": 1}
  ]
}
```

### `POST /api/v1/validate` — 结构校验

请求体与展开接口相同。无论是否合法都返回 **200**，由 `valid` 字段标识，
并一次性给出全部 `errors`、`warnings` 以及解析出的 `repeat_sections`（便于人工核对）：

```bash
curl -s http://localhost:8000/api/v1/validate \
  -H 'Content-Type: application/json' \
  -d '{"measures":[{"measure":1,"repeat_start":true},{"measure":2}]}'
```

```json
{
  "valid": false,
  "errors": [
    {"code": "UNCLOSED_REPEAT", "message": "存在未闭合的左反复记号 |:（缺少配对的 :|）", "measure": 1}
  ],
  "warnings": [],
  "repeat_sections": []
}
```

## 演奏语义约定

1. `:|` 使当前反复段再奏，直到奏满声明遍数；嵌套反复在外层第二遍中已“完成”，
   内层不再重复。
2. 结尾小节只在“结尾号 == 当前遍数”时演奏，其余跳过。非最后一个结尾的末尾
   必须有 `:|`；最后一个结尾后的 `:|` 可省略（反复段在该结尾末尾隐式闭合）。
3. 按常见演奏惯例，**D.C./D.S. 折返后不再重复此前已奏过的反复段**
   （直接走最后一个结尾）；Fine / To Coda 只在折返后的第二遍生效，
   首遍经过 Fine / To Coda 时忽略。
4. 一首乐曲至多一个 D.C./D.S. 指令、一个 Segno / Coda / Fine / To Coda 目标点；
   `al Fine` 必须有 Fine，`al Coda` 必须有 To Coda 与 Coda。
5. Fine / To Coda / D.C./D.S. 指令必须位于反复段与结尾之外（不能写在反复小节杠
   或房子内），以保证跳转无歧义。

## 主要错误码

| code | 触发场景 |
| --- | --- |
| `UNCLOSED_REPEAT` / `UNCLOSED_ENDING` | 未闭合的 `|:` / 结尾没有包围反复段 |
| `MISSING_END_REPEAT` | 非最后结尾末尾缺少 `:|` |
| `ENDING_NUMBER_SEQUENCE` / `ENDING_NUMBER_MISSING` | 结尾编号不连续 / 缺编号 |
| `REPEAT_TIMES_ENDING_MISMATCH` | 反复遍数与结尾数不一致 |
| `MARKER_ON_REPEAT_BAR` / `MARKER_INSIDE_ENDING` / `NAVIGATION_INSIDE_REPEAT` | 非法标记位置 |
| `MISSING_SEGNO` / `MISSING_FINE` / `MISSING_TO_CODA` / `MISSING_CODA` | 跳转目标缺失 |
| `SEGNO_AFTER_NAVIGATION` / `FINE_AFTER_NAVIGATION` / `CODA_BEFORE_NAVIGATION` | 非法跳转顺序 |
| `MULTIPLE_NAVIGATION` / `AMBIGUOUS_*` | 多个指令或多个同名目标点 |
| `MAX_STEPS_EXCEEDED` | 展开步数超过请求的 `max_steps`（错误带当前小节定位） |
| `MAX_STEPS_TOO_LARGE` | 请求的 `max_steps` 超过服务端硬上限 |

## 测试

```bash
pip install -r requirements.txt pytest httpx
pytest -q
```

## 项目结构

```
app/
  main.py       # FastAPI 路由：/api/v1/expand、/api/v1/validate、/health
  analyzer.py   # 静态结构分析：反复段 / 结尾 / 导航标记解析与校验
  expander.py   # 演奏语义虚拟机：生成实际小节序列
  models.py     # Pydantic 请求/响应模型
  config.py     # 环境变量配置
  errors.py     # 带小节定位的错误类型
tests/
  test_api.py
Dockerfile
docker-compose.yml
```
