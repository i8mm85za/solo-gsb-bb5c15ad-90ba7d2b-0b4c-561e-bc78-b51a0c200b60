# 乐谱反复路径展开 API

基于 FastAPI 的乐谱反复结构展开服务。请求提交按小节排列的结构标记（成对反复、
第一/第二结尾、D.C./D.S. al Coda/Fine），服务按演奏语义生成实际演奏的小节序列，
并为每一步保留原始小节号。遇到未闭合反复、非法跳转或超过最大展开步数时，返回
带小节定位的错误，且不产出部分序列。

## 启动

```bash
docker compose up --build
```

一条命令完成依赖安装与服务启动（依赖在镜像构建阶段装入，容器启动即可用）。

- 服务地址： http://localhost:8000
- 交互式文档（Swagger UI）： http://localhost:8000/docs
- 健康检查： http://localhost:8000/health

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_EXPAND_STEPS` | `1000` | 服务端最大展开步数上限；请求里的 `max_steps` 只能比它小 |

在 `docker-compose.yml` 的 `environment` 中修改即可。端口映射为 `8000:8000`，
如需更换宿主机端口，改 `ports` 的第一段。

## 接口

### `POST /expand` — 展开

请求体：

```json
{
  "title": "示例",
  "max_steps": 500,
  "measures": [
    {"number": 1},
    {"number": 2, "markers": ["repeat_begin"]},
    {"number": 3},
    {"number": 4, "markers": ["ending_begin"], "ending_numbers": [1]},
    {"number": 5, "markers": ["ending_end", "repeat_end"]},
    {"number": 6, "markers": ["ending_begin"], "ending_numbers": [2]},
    {"number": 7, "markers": ["ending_end"]},
    {"number": 8}
  ]
}
```

响应（`steps` 中每个元素都带原始小节号 `measure`，`action`/`jump_to` 标注跳转）：

```json
{
  "title": "示例",
  "measure_count": 8,
  "total_steps": 10,
  "max_steps": 500,
  "steps": [
    {"step": 1, "measure": 1, "action": null, "jump_to": null},
    {"step": 2, "measure": 2, "action": null, "jump_to": null},
    {"step": 3, "measure": 3, "action": null, "jump_to": null},
    {"step": 4, "measure": 4, "action": null, "jump_to": null},
    {"step": 5, "measure": 5, "action": "repeat_back", "jump_to": 2},
    {"step": 6, "measure": 2, "action": null, "jump_to": null},
    {"step": 7, "measure": 3, "action": null, "jump_to": null},
    {"step": 8, "measure": 6, "action": null, "jump_to": null},
    {"step": 9, "measure": 7, "action": null, "jump_to": null},
    {"step": 10, "measure": 8, "action": null, "jump_to": null}
  ],
  "warnings": []
}
```

失败时返回 HTTP 422，只含错误列表（带小节定位），不含任何部分序列：

```json
{
  "errors": [
    {"code": "UNCLOSED_REPEAT", "message": "repeat_begin is never closed by repeat_end", "measure": 2}
  ]
}
```

### `POST /validate` — 结构校验

请求体与 `/expand` 相同，只校验不展开：

```json
{
  "valid": false,
  "errors": [{"code": "DS_WITHOUT_SEGNO", "message": "...", "measure": 6}],
  "warnings": [{"code": "UNUSED_FINE", "message": "...", "measure": 3}]
}
```

### `GET /health` — 健康检查

## 小节标记

| marker | 含义 |
| --- | --- |
| `repeat_begin` | 反复开始 `|:` |
| `repeat_end` | 反复结束 `:|`，可配 `repeat_times`（总演奏遍数，默认 2，上限 64）；无配对的 `repeat_end` 表示从头反复 |
| `ending_begin` | 结尾（volta）开始，必须同时给 `ending_numbers`，如 `[1]`、`[1,2]` |
| `ending_end` | 结尾结束 |
| `segno` | 𝄋 记号（全曲至多一个） |
| `fine` | Fine 终止处 |
| `to_coda` | “to Coda” 跳转点 |
| `coda_sign` | Coda 段落起点 |
| `dc_al_fine` / `dc_al_coda` | 从头反复至 Fine / 至 Coda |
| `ds_al_fine` / `ds_al_coda` | 从 𝄋 反复至 Fine / 至 Coda |

演奏语义约定：

- 反复段按 `repeat_times` 演奏；结尾按所属反复段的当前遍数选择，不在
  `ending_numbers` 中的结尾被跳过；
- 多结尾中每个非末尾结尾自带的 `:|` 视为同一反复段的延续（标准记谱）；
- D.C. 回到第 1 小节，D.S. 回到 `segno`；跳转指令全曲至多一条且只执行一次；
- 跳转之后反复记号不再执行（按惯例直奏），结尾仍按遍数计数器选择；
- `al Fine` 在 `fine` 处结束；`al Coda` 在 `to_coda` 处跳到 `coda_sign` 并奏至曲终。

## 错误码

| code | 含义 |
| --- | --- |
| `UNCLOSED_REPEAT` | `repeat_begin` 没有配对的 `repeat_end` |
| `UNCLOSED_ENDING` / `ENDING_END_WITHOUT_BEGIN` / `NESTED_ENDING` | 结尾括号不配对或嵌套 |
| `ENDING_NUMBERS_MISSING` | `ending_begin` 缺少 `ending_numbers` |
| `ENDING_WITHOUT_REPEAT` | 结尾不属于任何反复段 |
| `DUPLICATE_MEASURE` / `DUPLICATE_MARKER` | 小节号或唯一性记号重复 |
| `DS_WITHOUT_SEGNO` / `MISSING_FINE` / `MISSING_TO_CODA` / `MISSING_CODA_SIGN` | 跳转目标记号缺失 |
| `ILLEGAL_JUMP` | 跳转目标位置不合法（如 segno 在 D.S. 之后、coda_sign 在 to_coda 之前） |
| `MULTIPLE_JUMPS` | 全曲出现多条 D.C./D.S. 指令 |
| `INVALID_REPEAT_TIMES` | `repeat_times` 超出 1–64 |
| `MAX_STEPS_EXCEEDED` | 展开超过最大步数限制 |

## 本地开发与测试

```bash
pip install -r requirements-dev.txt
pytest                       # 全部测试（引擎 + API）
python3 -m unittest discover -s tests   # 仅引擎测试（零依赖，标准库即可运行）
uvicorn app.main:app --reload --port 8000
```
