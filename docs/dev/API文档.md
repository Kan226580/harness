# 工程标书 AI Harness Agent API 文档

> 版本：v1.0 ｜ 日期：2026-10-07 ｜ 状态：接口合同，尚未实现
>
> 上游：[开发方案.md](./开发方案.md)、[开发文档.md](./开发文档.md)。持久化字段见 [数据库文档.md](./数据库文档.md)。

## 1. 通用约定

### 1.1 传输与字段

- Base URL：同源 `/api/v1`；公网只允许 HTTPS。
- 普通请求使用 JSON，上传使用 multipart/form-data，下载与 SSE 使用专门类型。
- ID 为 UUID 字符串；示例 UUID 只是占位数据。
- JSON 字段使用 snake_case；拒绝未定义的请求字段。
- 时间使用 UTC ISO 8601，例如 `2026-10-07T02:30:00Z`；前端按 Asia/Shanghai 显示。
- 纯日期为 YYYY-MM-DD。页码从 1 起，段落／表格／行列序号从 0 起。
- 费用和分值使用十进制字符串，例如 `"10.000000"`、`"5.00"`；Token、版本号和计数使用整数。
- 对不存在或属于其他组织的资源统一返回 404，不暴露存在性。
- v1 不提供公开注册、任意 URL 导入、任意 SQL 或代码执行接口。
- 下文所有接口均为计划合同；实现后由 Pydantic 生成 OpenAPI 并进行合同测试。

### 1.2 成功与错误响应

除文件、SSE 和 204 外，成功响应使用统一外壳：

```json
{
  "data": {"id": "11111111-1111-4111-8111-111111111111"},
  "request_id": "22222222-2222-4222-8222-222222222222"
}
```

列表响应：

```json
{
  "data": {
    "items": [],
    "next_cursor": null,
    "has_more": false
  },
  "request_id": "22222222-2222-4222-8222-222222222222"
}
```

错误响应：

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "内容已更新，请比较最新版本后重新保存。",
    "details": {"current_lock_version": 4},
    "retryable": false
  },
  "request_id": "22222222-2222-4222-8222-222222222222"
}
```

认证或跨组织错误不返回资源细节；错误详情不包含堆栈、原文、密钥和完整提示词。字段错误在 details.fields 中提供 field 与 reason。

### 1.3 分页与查询

列表支持 limit（默认 20，1–100）和 cursor。采用稳定游标分页，默认按 created_at DESC、id DESC 排序；章节按 position、id 排序。

cursor 是服务端编码的过滤条件摘要与排序锚点。改变过滤条件后必须重新开始；无效 cursor 返回 422。默认不计算 total，避免无必要的大范围 count。

名称查询 q 长度 1–100；检索正文 query 长度 1–2,000。API 响应中的 org_id 如需展示由服务端赋值，任何请求不能指定 org_id。

### 1.4 认证、CSRF 与限流

- 会话 Cookie 名称 bid_session，HttpOnly、生产 Secure、SameSite=Lax，默认 12 小时有效。
- 登录、修改密码会轮换会话标识。登出撤销当前会话。
- 登录返回 csrf_token，GET /auth/me 也可取得当前 Token。
- 登录之外的 POST、PATCH、DELETE 要求 `X-CSRF-Token`；所有浏览器写请求校验 Origin。
- 登录按入口 IP 限流，账号连续失败五次锁定 15 分钟；统一返回认证失败，不披露账号是否存在。
- 默认同账号普通请求每分钟 120 次，上传每分钟 10 次；运行创建每分钟 10 次。超限 429 并带 Retry-After。
- 文件和 SSE 使用会话认证，不能在 URL 中传 Cookie、密钥或身份 Token。

### 1.5 幂等与并发

标注为“幂等必需”的接口要求 Idempotency-Key，长度 8–128 的 ASCII 字符。作用域包含组织、用户、方法和规范化路径。

| 条件 | 行为 |
|---|---|
| 同 key、相同请求摘要、已完成 | 返回原状态码与响应，附 Idempotency-Replayed: true |
| 同 key、不同请求摘要 | 409 IDEMPOTENCY_CONFLICT |
| 同 key 正在处理 | 409 IDEMPOTENCY_IN_PROGRESS，带 Retry-After |
| 记录超过 24 小时 | 可作为新请求；不能据此推断原成果不存在 |

创建运行、恢复、取消、重试、发布基准、审核和导出要求幂等键。上传不要求幂等键，超时后先查询文件版本，不盲目重复上传。

更新可变业务记录要求 expected_lock_version；冲突返回 409 VERSION_CONFLICT。单纯后台解析进度变化不递增用户编辑锁版本。幂等机制不能代替版本冲突校验。

## 2. 权限模型

缩写：A=admin，W=writer，R=reviewer。admin 包含编写和审核能力，但不得自审。项目内容在组织内共享，不提供跨组织访问。

| 操作 | 权限 |
|---|---|
| 阅读项目、资料、章节、运行、报告 | A / W / R |
| 创建和编辑项目、资料、要求、事实、基准、章节 | A / W |
| 生成、取消生成、恢复生成 | A / W |
| 发起审查 | A / W / R |
| 审查人工处置与审核 | A / R |
| 导出审阅版 | A / W / R |
| 导出提交草稿 | A / R，且全部审核条件通过 |
| 成员管理、项目归档、组织配置 | A |
| 查看项目审计记录 | A / R |

运行取消和 retry 还按类型检查权限：parse/index/analyze/generate 要求 A/W，review 任一业务角色，export 按导出模式。管理员不绕过项目状态、许可或审核条件。

## 3. 公共对象

### 3.1 User、Project

| 对象 | 字段 |
|---|---|
| User | id、email、display_name、role、is_active、must_change_password、lock_version、created_at |
| Project | id、name、construction_type、description、data_classification、status、current_baseline_id、baseline_dirty、lock_version、created_by、created_at、updated_at |

data_classification：synthetic、deidentified、confidential。status：active、archived。

baseline_dirty 表示要求、事实、资料可用性或目录配置已改变，尚未重新发布基准。脏基准不能新建或恢复生成，也不能批准版本或导出提交草稿。

### 3.2 Document、DocumentVersion、DocumentBlock

| 对象 | 字段 |
|---|---|
| Document | id、project_id（可空）、title、kind、status、current_version_id、lock_version、created_at |
| DocumentVersion | id、document_id、version_no、original_filename、media_type、byte_size、sha256、parse_status、verification_status、index_status、embedding_available、allow_external_processing、permission_note、parser_version、lock_version、created_at |
| DocumentBlock | id、document_version_id、ordinal、block_type、heading_path、text、table_data、source_locator |

kind：tender、enterprise、historical、reference。status：active、archived。tender 必须绑定 project_id，其他类型允许组织共享。

source_locator 的判别字段为 format：

```json
{
  "format": "pdf",
  "page": 12,
  "regions": [{"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3}],
  "heading_path": ["评标办法", "技术评分"]
}
```

PDF 区域为页面左上角原点的 0–1 归一化坐标；没有可靠区域时 regions 为空，但 page 必须真实存在。

```json
{
  "format": "docx",
  "heading_path": ["施工组织设计", "安全保障"],
  "paragraph_index": null,
  "table_index": 2,
  "row_index": 1,
  "column_index": 0
}
```

DOCX 的段落位置与单元格位置二选一，未使用字段为 null，不提供 page。

### 3.3 Requirement、ProjectFact、Baseline

| 对象 | 字段 |
|---|---|
| Requirement | id、project_id、title、original_text、response_guidance、category、score_max、status、source_type、source_block_id、manual_source_note、allow_external_processing、lock_version |
| ProjectFact | id、project_id、fact_key、label、value_json、unit、fact_kind、status、source_type、source_block_id、manual_source_note、allow_external_processing、lock_version |
| Baseline | id、project_id、version_no、snapshot_hash、snapshot_json、published_by、published_at、is_current、source_status |

category：mandatory、scoring、general。status：draft、confirmed、rejected。source_type：document、manual。fact_kind：tender、enterprise。

document 来源必须给 source_block_id，外发许可以当前来源文件为准；manual 来源必须给说明，allow_external_processing 表示人工输入的外发许可，默认 false。

snapshot_json 固定包含 requirements、facts、document_versions、chapter_assignments；每个数组复制实际值与来源，不只保存 ID。source_status 为 valid、changed、unavailable，实时计算，不写回不可变快照。

### 3.4 Chapter、ChapterVersion 与引用

| 对象 | 字段 |
|---|---|
| Chapter | id、project_id、parent_id、title、chapter_type、position、selected_version_id、needs_review、requirement_ids、lock_version |
| ChapterVersion | id、chapter_id、version_no、baseline_id、origin、content_json、content_plain、content_hash、has_placeholders、model_mode、source_run_id、created_by、created_at、citations、requirement_responses |

chapter_type：construction、schedule、quality、safety、resources、custom。origin：manual、generated。model_mode：cloud、simulated、none；manual 为 none。

content_json 使用开发文档限定的 Tiptap Schema，每个可引用节点具有 block_id。requirement_responses 为 requirement_id、response_status、note 数组；response_status 使用 complete、partial、missing、needs_confirmation。

Citation：id、content_block_id、source_block_id、claim_text、support_status。support_status：confirmed、needs_confirmation、invalid。source_locator 在读取时通过来源块返回，客户端不能提交自造页码。

has_placeholders 由服务端根据显式待补项标记及校验结果计算，不能依赖客户端声明。内容版本不可 PATCH，修改必须创建新版本。

### 3.5 Run

| 字段 | 含义 |
|---|---|
| id、project_id、kind、chapter_id | 运行与目标 |
| status、cancel_requested | 状态和取消请求 |
| current_step、completed_steps、total_steps | 阶段进度，不承诺精确耗时百分比 |
| baseline_id、snapshot_hash、model_mode | 冻结配置 |
| retry_of_run_id | 失败运行重试来源 |
| budget | max_calls、max_tokens、max_cost_cny |
| usage | call_count、tokens_observed、tokens_reserved、cost_observed_cny、cost_reserved_cny、has_unknown_calls |
| input_required | 需要人工输入时的结构化内容，其他状态 null |
| artifact | 成果 type 与 id，未完成时 null |
| error | code、message、retryable，成功时 null |
| last_event_seq、created_at、started_at、finished_at | 事件游标与时间 |

kind：parse、index、analyze、generate、review、export。status：queued、running、waiting_input、retry_wait、succeeded、failed、canceled。

artifact.type 为 document_version、analysis_batch、chapter_version、review_report、export。parse/index 指向资料版本；analysis_batch 的 id 为运行 ID，可按 source_run_id 查询抽取的要求与事实；generate/review/export 分别指向对应成果记录。

租约 owner、fencing token、Cookie、供应商密钥、Checkpoint 原始内容不出现在用户响应中。

### 3.6 ReviewReport、Finding、Approval、Export

| 对象 | 字段 |
|---|---|
| ReviewReport | id、project_id、baseline_id、run_id、status、target_versions、summary_json、created_at、completed_at |
| Finding | id、report_id、chapter_version_id、requirement_id、content_block_id、category、severity、description、evidence_json、suggestion、status、resolution_note、resolved_by、lock_version |
| Approval | id、chapter_version_id、baseline_id、report_id、action、comment、created_by、created_at |
| Export | id、project_id、baseline_id、run_id、mode、status、template_version、filename、sha256、byte_size、items、is_stale、created_at |

报告 status：pending、completed、failed。finding severity：blocker、high、medium、low；status：open、resolved、accepted。finding category：requirement_response、fact_conflict、evidence_issue、completeness、style、standard_applicability。approval action：approve、request_changes。

导出 mode：review、submission_draft；status：pending、generating、ready、failed。target_versions 与 items 均指明 chapter_id、chapter_version_id 和顺序。

## 4. 认证与成员接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| POST /auth/login | 匿名，Origin 校验 | 创建会话，200 |
| GET /auth/me | 已登录 | 当前用户、组织摘要、csrf_token，200 |
| POST /auth/logout | 已登录 | 撤销会话，204 |
| POST /auth/password | 已登录 | 修改密码，200 |
| GET /members | A | 分页成员列表 |
| POST /members | A | 创建本组织账号，201 |
| PATCH /members/{user_id} | A | 角色／停用，200 |
| GET /organization/settings | A | 读取公开运行配置 |
| PATCH /organization/settings | A | 修改组织配额，200 |

登录请求：

```json
{
  "organization_slug": "demo-construction",
  "email": "writer@example.invalid",
  "password": "示例占位密码，请在实际部署时设置"
}
```

响应 data 为 user、organization（id、slug、name）、csrf_token；通过 Set-Cookie 下发会话。登录失败统一 AUTHENTICATION_FAILED，401。

修改密码：current_password、new_password，长度 12–128；成功轮换当前会话、撤销其他会话，返回新 csrf_token。must_change_password 为 true 时除 me、logout、password 外的业务操作返回 PASSWORD_CHANGE_REQUIRED。

创建成员：email、display_name（1–50）、role、temporary_password。临时密码仅在请求中使用，不能回显；账号 must_change_password=true。邮箱在本组织冲突时 409。

修改成员：expected_lock_version 必填，role、is_active 至少一个；不能移除最后一个管理员。v1 不提供管理员读取或重置其他成员明文密码的接口。

组织设置响应包含 lock_version、run_max_calls、run_max_tokens、run_max_cost_cny。修改字段：expected_lock_version、run_max_calls（1–12）、run_max_tokens（1–60,000）、run_max_cost_cny（正十进制字符串或 null）。默认调用／Token 上限为 12／60,000；费用上限初始为 null，cloud 模式始终需要定价配置以记录估算。供应商密钥和数据库连接不通过该接口设置。

## 5. 项目接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET /projects | A/W/R | q、status 过滤 |
| POST /projects | A/W | 创建项目与默认五章，201 |
| GET /projects/{project_id} | A/W/R | 详情 |
| PATCH /projects/{project_id} | A/W | 编辑基本信息 |
| POST /projects/{project_id}/archive | A | 归档，幂等必需 |

创建项目：name（1–200）、construction_type（1–100）、description（可选，≤2,000）、data_classification（默认 synthetic）。创建后 current_baseline_id=null、baseline_dirty=true。

修改项目：expected_lock_version 必填，其余同创建可选；名称与工程类型变化会设置 baseline_dirty=true 并标记章节复核。归档请求只含 expected_lock_version，存在非终态运行时 409 RUNS_ACTIVE。

## 6. 文档与文件接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET /documents | A/W/R | project_id、kind、status、q；include_shared=true 可含组织共享资料 |
| POST /documents | A/W | 新文件＋parse 运行，202 |
| GET /documents/{document_id} | A/W/R | 文件与版本摘要 |
| PATCH /documents/{document_id} | A/W | 标题或归档 |
| POST /documents/{document_id}/versions | A/W | 上传新版本＋parse 运行，202 |
| GET /document-versions/{version_id} | A/W/R | 文件版本元数据 |
| PATCH /document-versions/{version_id}/verification | A/W | 确认／拒绝／外发许可；必要时触发 index，202 |
| GET /document-versions/{version_id}/file | A/W/R | 受权读取原件 |
| GET /document-versions/{version_id}/blocks | A/W/R | 按 ordinal 排列解析块 |
| GET /document-blocks/{block_id} | A/W/R | 单块、定位与文件访问路径 |
| POST /document-versions/{version_id}/parse-runs | A/W | 重试失败解析，202，幂等必需 |
| POST /document-versions/{version_id}/index-runs | A/W | 重建索引，202，幂等必需 |

上传 form 字段：file、title（≤200）、kind、project_id（可空）、permission_note（可选）。默认 verification_status=draft、allow_external_processing=false。上传后必须单独确认外发许可。

上传版本还要求 expected_lock_version；成功增加逻辑 Document 的 lock_version 并更新 current_version_id，但不替换已发布 baseline 的旧版本。v1 同一 Document 新版本不得改变 kind、project_id 或媒体格式。

上传响应：

```json
{
  "data": {
    "document_id": "11111111-1111-4111-8111-111111111111",
    "document_version_id": "33333333-3333-4333-8333-333333333333",
    "run_id": "44444444-4444-4444-8444-444444444444",
    "status": "queued"
  },
  "request_id": "22222222-2222-4222-8222-222222222222"
}
```

默认单文件 50 MiB，PDF 400 页。超大小 413；非 PDF/DOCX 415；扫描、加密、损坏或资源限制问题可能在 parse 运行中失败，错误记录到 run，不将上传接受误认为解析成功。

verification 请求：expected_lock_version、verification_status（confirmed 或 rejected）、allow_external_processing（默认保持现值）、permission_note（许可变更或拒绝时必填，≤1,000）。确认要求 parsed；未完成解析时 409。

确认后构建词项索引；获准外发且 cloud 配置完整才构建向量。响应 data 为 version、run_id（无任务时 null）。撤销许可立即影响新调用，并将使用该资料的项目 baseline_dirty=true。

文档归档要求 expected_lock_version；归档后影响关联基准。查看原件仍可用于组织内历史复核，检索和生成排除归档资料。

文件响应支持 Content-Disposition 与标准 Range 单区间请求，返回 200 或 206；无效区间 416。PDF 可 inline，DOCX 默认 attachment。下载接口不返回内部 bucket、object_key 或长期公开 URL。

重新 parse 仅限 failed/unsupported，成功结果不可原地重解析，应上传新版本。index-runs 要求 parsed+confirmed，避免相同配置的并发索引，冲突返回 409。

## 7. 招标分析、要求、事实与基准接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| POST /projects/{project_id}/analysis-runs | A/W | 分析招标版本，202，幂等必需 |
| GET /projects/{project_id}/requirements | A/W/R | status、category、source_run_id 过滤 |
| POST /projects/{project_id}/requirements | A/W | 人工新增，201 |
| PATCH /requirements/{requirement_id} | A/W | 修订、确认或拒绝 |
| GET /projects/{project_id}/facts | A/W/R | status、fact_kind、source_run_id 过滤 |
| POST /projects/{project_id}/facts | A/W | 人工新增，201 |
| PATCH /facts/{fact_id} | A/W | 修订、确认或拒绝 |
| GET /projects/{project_id}/baselines | A/W/R | 历史基准 |
| POST /projects/{project_id}/baselines | A/W | 发布新基准，201，幂等必需 |
| GET /baselines/{baseline_id} | A/W/R | 不可变快照与实时有效性 |

analysis-runs 请求：document_version_ids（1–10）、budget（可选）。只能来自当前项目 tender 文件且 parsed+confirmed。cloud 模式要求外发许可，否则 403 DATA_EXTERNAL_NOT_ALLOWED。

重新分析同一文件不会修改人工确认结果；新的抽取记录 source_run_id，按来源与语义指纹去重。已有 confirmed 记录发生差异时列为新 draft 待人工处理。

人工要求创建字段：title、original_text（≤10,000）、response_guidance（≤5,000）、category、score_max（可空）、source_type、source_block_id（可空）、manual_source_note（可空）、allow_external_processing（默认 false）。状态初始 draft。

人工事实字段：fact_key（1–100）、label（≤200）、value_json、unit（≤50，可空）、fact_kind、source_type、source_block_id、manual_source_note、allow_external_processing。value_json 使用 value_type 与 value：text、number、date、boolean、list；number 的 value 为十进制字符串。

事实示例：

```json
{
  "fact_key": "contract_duration_days",
  "label": "要求工期",
  "value_json": {"value_type": "number", "value": "180"},
  "unit": "天",
  "fact_kind": "tender",
  "source_type": "document",
  "source_block_id": "55555555-5555-4555-8555-555555555555"
}
```

修订请求要求 expected_lock_version，可以修改上述字段和 status；改动后项目 baseline_dirty=true。enterprise 事实的 document 来源只能是 enterprise；tender 事实只能来自项目 tender，不能从 historical 自动确认。

发布 baseline 请求：expected_project_lock_version、document_version_ids（1–50）、note（≤1,000，可选）。包含所有 confirmed 要求、事实和当前章节要求映射，拒绝遗漏这些记录的来源版本。每个来源文件必须 parsed、confirmed、active。

发布后返回 Baseline，项目 baseline_dirty=false。旧基准保留，新基准下所有章节 needs_review=true。重复相同幂等键返回原 baseline；相同内容且当前已有同哈希基准时返回当前基准，不重复增版。

## 8. 检索接口

**POST /projects/{project_id}/search**，A/W/R，200。

| 请求字段 | 约束 |
|---|---|
| query | 1–2,000 字符 |
| mode | lexical / hybrid，默认 lexical |
| allow_external_query | 默认 false；cloud hybrid 要求 true |
| kinds | 可选资料类型数组 |
| baseline_id | 可空；给定后限制冻结资料版本 |
| limit | 默认 10，1–20 |

响应 data：items、mode_used、fallback_reason、model_mode、index_profile_id。每条 item 包含 block、document_title、document_kind、document_version_id、ranking_score、embedding_available。

hybrid 查询可能将查询文本发给云端，因此需要明确许可。向量不可用时返回 mode_used=lexical 与原因，不把词项结果冒充向量结果。检索结果仅来自本组织的项目资料或共享资料。

引用在生成时由服务器从已授权结果映射，不允许模型提交任意资料 ID 获得访问。

## 9. 章节与版本接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET /projects/{project_id}/chapters | A/W/R | 完整目录树与状态，200 |
| POST /projects/{project_id}/chapters | A/W | 新节点，201 |
| PATCH /chapters/{chapter_id} | A/W | 修改标题、类型、顺序、父节点 |
| PATCH /chapters/{chapter_id}/requirements | A/W | 替换当前要求映射 |
| GET /chapters/{chapter_id}/versions | A/W/R | 分页版本摘要 |
| POST /chapters/{chapter_id}/versions | A/W | 人工保存新版本并选用，201 |
| GET /chapter-versions/{version_id} | A/W/R | 完整内容、要求响应、引用 |
| POST /chapters/{chapter_id}/selection | A/W | 显式采用版本 |
| GET /chapters/{chapter_id}/comparison | A/W/R | 比较 from_version_id、to_version_id |
| GET /chapters/{chapter_id}/approvals | A/W/R | 审核记录 |

创建章节字段：title（1–200）、chapter_type、parent_id（可空）、position（非负）。层级最大三层，同级 position 不允许相同；修改目录配置将 baseline_dirty=true。

requirements 请求：expected_lock_version、requirement_ids（≤100，同项目、不重复）。映射变化需要重新发布基准。

人工保存请求：

```json
{
  "expected_lock_version": 3,
  "baseline_id": "66666666-6666-4666-8666-666666666666",
  "content_json": {
    "type": "doc",
    "content": [
      {
        "type": "paragraph",
        "attrs": {"block_id": "p-001"},
        "content": [{"type": "text", "text": "拟按经确认的工期目标组织施工。"}]
      }
    ]
  },
  "citations": [],
  "requirement_responses": []
}
```

baseline_id 可为 null，表示未建立基准的手工草稿；生成与审核不能使用 null 基准版本。保存原子建立版本并选用，返回 version 和 chapter_lock_version。

content_json 最大 1 MiB、最大节点深度 12、正文最多 100,000 字符。citations 中只允许 content_block_id、source_block_id、claim_text、support_status，不允许客户端设置 Citation ID 或来源页码。每个引用必须对应正文节点和同项目／共享资料。

selection 请求：expected_lock_version、version_id。版本必须属于本章，返回 Chapter；即使选用旧版本也设置 needs_review=true。

comparison 响应为 from_version、to_version 摘要和 changes（added、removed、modified 的块级差异）。两版本必须同章。

v1 不提供删除章节接口，避免破坏历史导出和引用；需要删除能力时单独设计归档与迁移。

## 10. 运行接口

### 10.1 创建生成运行

**POST /projects/{project_id}/generation-runs**，A/W，202，幂等必需。

```json
{
  "chapter_id": "77777777-7777-4777-8777-777777777777",
  "baseline_id": "66666666-6666-4666-8666-666666666666",
  "expected_chapter_lock_version": 4,
  "instructions": "突出本工程的关键施工工序和质量控制措施。",
  "allow_placeholders": false,
  "budget": {"max_calls": 10, "max_tokens": 50000, "max_cost_cny": null}
}
```

instructions ≤2,000，仅作为写作偏好，不改变安全规则。baseline 必须当前且非 dirty；章节映射和来源有效。预算省略时使用组织上限，请求只能下调不能提高；费用上限可在组织允许范围内进一步收紧。

成功响应：run_id、status、events_url、status_url。每次只生成一章；第三条运行可以 queued，最多两章同时获得执行租约。

### 10.2 查询与控制

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| GET /projects/{project_id}/runs | A/W/R | kind、status 过滤 |
| GET /runs/{run_id} | A/W/R | Run 对象 |
| GET /runs/{run_id}/events | A/W/R | SSE，200 |
| POST /runs/{run_id}/resume | 按类型 | waiting_input 恢复，202，幂等必需 |
| POST /runs/{run_id}/cancel | 按类型 | 请求取消，202，幂等必需 |
| POST /runs/{run_id}/retry | 按类型 | failed 新建运行，202，幂等必需 |

resume 请求：

```json
{
  "decision": "proceed_with_placeholders",
  "acknowledged_gap_ids": ["gap-001"],
  "note": "保留待补项，后续由编写人员补充。"
}
```

必须确认所有当前 gap；note 1–1,000。不能通过 resume 传新事实、文件 ID 或模型配置。decision=cancel 等价请求取消。基准脏时 409 BASELINE_DIRTY，已经更换时 409 BASELINE_STALE。

cancel 请求：reason（可选，≤500）。queued、waiting_input、retry_wait 可立即取消；running 只设置 cancel_requested，返回当前状态，不声称远端调用已撤回。succeeded/failed 不能转 canceled，返回 409 RUN_TERMINAL；已 canceled 的重复取消返回当前运行。

retry 请求：reason（可选），只接受 failed 运行。返回新的 run_id 和 retry_of_run_id，沿用原输入快照并重新检查当前基准与许可；原 run 保留 failed。parse/index 的 retry 同样创建新运行并复用目标版本；成功产物不得重复插入。

### 10.3 SSE 合同

Content-Type 为 text/event-stream，Cache-Control=no-cache，代理关闭缓冲。每 15 秒发送注释心跳；事件从 run_events 读取，不以 Redis Pub/Sub 为唯一来源。

支持 Last-Event-ID，格式 `run_id:seq`；首次可使用 after_seq 查询参数（默认 0）。两者同时提供时 Last-Event-ID 优先。非法或其他运行的 ID 返回 422。

```text
id: 44444444-4444-4444-8444-444444444444:8
event: run.waiting_input
data: {"run_id":"44444444-4444-4444-8444-444444444444","seq":8,"status":"waiting_input","payload":{"gap_ids":["gap-001"]},"created_at":"2026-10-07T02:30:00Z"}

```

事件名称：run.queued、run.started、step.started、step.completed、run.waiting_input、run.resumed、run.retry_scheduled、run.cancel_requested、run.canceled、run.failed、run.succeeded、usage.updated。

序号单调递增，客户端按 seq 去重；并不要求全球连续。终态事件发送后关闭连接；客户端随后查询最终 Run。waiting_input 发送后也关闭连接，恢复后重新连接。

保留事件默认 30 天。after_seq 早于保留窗口时，在打开流前返回 410 EVENT_HISTORY_EXPIRED，客户端重新获取 Run 并使用最新游标。会话过期或账号停用后停止继续发送，不在流中泄漏其他组织状态。

## 11. 审查、问题处置与审核接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| POST /projects/{project_id}/review-runs | A/W/R | 发起审查，202，幂等必需 |
| GET /projects/{project_id}/review-reports | A/W/R | 报告列表 |
| GET /review-reports/{report_id} | A/W/R | 报告与响应摘要 |
| GET /review-reports/{report_id}/findings | A/W/R | severity、status 过滤 |
| PATCH /review-findings/{finding_id} | A/R | 处置允许的问题 |
| POST /chapter-versions/{version_id}/approvals | A/R | 审核，201，幂等必需 |

review-runs 请求：baseline_id、chapter_version_ids（1–50）、checks（可选，默认 rules 与 semantic）、budget（可选）。不能混合不同项目或基准。rules 可以本地执行；semantic 需要相应模型权限。

创建后返回 run_id、report_id、status。报告 completed 后才可用于审核，报告覆盖的版本不会随编辑变化。完成新报告会标记仍选用其目标版本的章节需要审核；最新报告按 completed_at DESC、id DESC 判断，不能引用旧报告避开新问题。

处置问题请求：expected_lock_version、status（resolved 或 accepted）、resolution_note（1–2,000）。blocker 均拒绝人工处置，返回 409 BLOCKER_REQUIRES_RECHECK。high 只允许 accepted；medium/low 可 resolved 或 accepted。

审核请求：

```json
{
  "expected_chapter_lock_version": 5,
  "baseline_id": "66666666-6666-4666-8666-666666666666",
  "report_id": "88888888-8888-4888-8888-888888888888",
  "action": "approve",
  "comment": "已核查工期、资料依据和评分要求响应。"
}
```

approve 的全部条件：当前基准非 dirty；版本当前选用且属于本章；报告为覆盖本版本和基准的最新 completed 报告；无待补项、无 invalid/needs_confirmation 引用、无 open blocker/high；审核者不是版本 created_by。

request_changes 要求 comment，设置 needs_review=true 并留记录；审核动作不修改正文。approve 成功将 needs_review=false。两种动作均递增章节 lock_version，响应 data 为 approval、chapter_lock_version。审核后产生新版本、变更选用、完成新审查或发布基准都需要再次审核。

## 12. 导出与审计接口

| 方法与路径 | 权限 | 说明 |
|---|---|---|
| POST /projects/{project_id}/exports | 按模式 | 创建导出，202，幂等必需 |
| GET /projects/{project_id}/exports | A/W/R | 导出记录 |
| GET /exports/{export_id} | A/W/R | 快照、状态和 is_stale |
| GET /exports/{export_id}/file | 按模式 | ready 文件下载 |
| GET /projects/{project_id}/audit-logs | A/R | 操作摘要与标识 |

导出请求：mode（review / submission_draft）、baseline_id（review 可空）、chapter_ids（1–50，顺序采用目录顺序）、template_version（v1 固定 technical-v1）、expected_project_lock_version。

review 允许未审核内容，必须有选定版本。submission_draft 要求当前有效基准、所有选定版本均在当前基准下获独立审核、无待补项、无需复核标记与未解决 blocker/high；失败返回 EXPORT_PRECHECK_FAILED 和可读的问题列表。

响应：export_id、run_id、status。文件未 ready 返回 409 EXPORT_NOT_READY，failed 返回该错误及运行查询路径。

提交草稿下载再次检查版本、基准、审核、资料许可和高等级问题。任一变化使条件不成立时返回 409 EXPORT_STALE，不把旧文件冒充当前可提交草稿。审阅版作为历史快照仍可下载。

下载只返回 DOCX 文件，不自动提交给任何投标平台。审计查询返回 actor、action、resource_type、resource_id、summary_json、created_at，不提供密码、原文或隐藏推理。

## 13. 健康检查

| 接口 | 访问 | 行为 |
|---|---|---|
| GET /health/live | 公开可用 | 进程存活，200；不披露配置 |
| GET /health/ready | 内网探针 | DB、迁移版本、必要存储与配置检查；200 / 503 |
| GET /metrics | 仅内网 | Prometheus 指标，公网代理阻断 |

这三个接口不使用 /api/v1 前缀。ready 不执行有费用的模型调用；Broker 临时失效可标记 degraded，但 outbox 允许运行创建后等待恢复。

## 14. 错误码清单

| HTTP | code | 场景 |
|---|---|---|
| 401 | AUTHENTICATION_FAILED / SESSION_EXPIRED | 登录失败或会话过期 |
| 403 | FORBIDDEN / CSRF_INVALID / PASSWORD_CHANGE_REQUIRED | 角色、CSRF、首次改密 |
| 403 | DATA_EXTERNAL_NOT_ALLOWED / DATA_PERMISSION_REVOKED | 外发许可不足或撤销 |
| 404 | RESOURCE_NOT_FOUND | 不存在或跨组织资源 |
| 409 | VERSION_CONFLICT | 用户更新锁不匹配 |
| 409 | IDEMPOTENCY_CONFLICT / IDEMPOTENCY_IN_PROGRESS | 幂等冲突或处理未完成 |
| 409 | PROJECT_ARCHIVED / RUNS_ACTIVE | 项目只读或归档有活动任务 |
| 409 | BASELINE_REQUIRED / BASELINE_STALE / BASELINE_DIRTY | 无基准、旧基准、未发布变更 |
| 409 | INVALID_STATE / RUN_TERMINAL | 操作不符合状态 |
| 409 | DOCUMENT_NOT_READY / INDEX_ALREADY_RUNNING | 解析、确认或索引条件不足 |
| 409 | SELF_APPROVAL_FORBIDDEN / REVIEW_REQUIRED | 自审或没有有效报告 |
| 409 | BLOCKER_REQUIRES_RECHECK | 试图手工绕过阻断问题 |
| 409 | EXPORT_PRECHECK_FAILED / EXPORT_NOT_READY / EXPORT_STALE | 导出条件或时效问题 |
| 410 | EVENT_HISTORY_EXPIRED | SSE 历史超保留期 |
| 413 | FILE_TOO_LARGE / CONTENT_TOO_LARGE | 上传或正文过大 |
| 415 | UNSUPPORTED_MEDIA_TYPE | 不支持格式 |
| 416 | RANGE_NOT_SATISFIABLE | 文件读取区间无效 |
| 422 | VALIDATION_ERROR / INVALID_REFERENCE | 字段、来源、跨项目关系错误 |
| 429 | RATE_LIMITED / BUDGET_EXCEEDED | 请求或预算超限 |
| 503 | MODEL_NOT_CONFIGURED / DEPENDENCY_UNAVAILABLE | 模型或必要依赖不可用 |

后台失败还使用 SCANNED_DOCUMENT_UNSUPPORTED、DOCUMENT_CORRUPTED、PARSER_LIMIT_EXCEEDED、MODEL_TIMEOUT、MODEL_RATE_LIMITED、MODEL_OUTPUT_INVALID、EMBEDDING_DIMENSION_MISMATCH、LEASE_RECOVERY_EXHAUSTED。这些写入 Run.error，不一定对应当前 HTTP 请求的状态码。

## 15. API 合同验收

- 每个角色的成功路径与禁止路径。
- 每个资源至少一个跨组织与同组织跨项目引用测试。
- 幂等相同请求、不同摘要、处理中和重放。
- 章节保存冲突、选用冲突、基准发布冲突、审核冲突。
- SSE 重连、过期游标、账号停用、终态与暂停关闭。
- 外发许可撤销、基准脏、旧报告、自己审核自己。
- 上传超限、扫描、损坏、DOCX 压缩炸弹、伪装扩展名。
- 导出审阅版允许待补，提交草稿拒绝待补和过期审核。
- OpenAPI 文档与实际响应合同一致，错误外壳和十进制字符串无漂移。

