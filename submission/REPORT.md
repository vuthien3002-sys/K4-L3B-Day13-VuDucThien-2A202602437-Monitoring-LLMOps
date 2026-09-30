# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Vũ Đức Thiện
- **MSSV:** 2A202602437
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/vuthien3002-sys/K4-L3B-Day13-VuDucThien-2A202602437-Monitoring-LLMOps
- **Commit SHA cuối:** `0b631e352ab69f428af5cd75e74abd81a0540403` là commit chứa toàn bộ source, config, báo cáo và evidence. Commit ngay sau nó chỉ ghi dòng SHA này (một commit không thể chứa SHA của chính nó); SHA nộp trên LMS là commit mới nhất trên `main` (`git log -1`).
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602437` (region EU, `https://cloud.langfuse.com`)

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png`, `evidence/08b-generation-usage-cost.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10a-prompt-after-promote.png`, `evidence/10b-prompt-after-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (thiếu correlation ID, thiếu enrichment) | 100/100 (111 records, 52 correlation ID, 0 PII) | CP1: middleware + bind context + `scrub_event`; đo trên log CP3 (log CP1–CP2 cũng đạt 100/100 với 413 records) |
| `validate_dashboard.py` | 6/6 panel hợp lệ | 6/6 panel hợp lệ | Dashboard runtime: `scripts/dashboard.py` |
| `pytest` | 22 passed | 37 passed | Thêm test PII, correlation ID, child observation, dashboard (kể cả zoom + ngưỡng challenge) |
| Số traces hợp lệ | 10 trace `lab-agent-run` (correlation_id=MISSING) | 60+ trace đủ cây `lab-agent-run` → `retrieval` + `generation` | Có `correlation_id`, prompt version, usage, cost |
| Số PII leak | 0 | 0 | Validator + test với email/SĐT/CCCD/thẻ |
| Latency P95 / TTFT P95 | 1405 ms / 50 ms | 3663 ms / 51 ms (cửa sổ 60 phút) | P95 vượt 3000 ms do mạng tới Langfuse chập chờn: TTFT không đổi, thời gian chậm nằm ở bước tải prompt (trace `9a6b3fb2…`: root bắt đầu 03:28:36, generation mới chạy 03:28:48) |
| Retrieval success rate | 100% (10/10, không có lỗi) | 100% | Chưa bật incident |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` gọi `clear_contextvars()` ở đầu mỗi request, nhận header `x-request-id` nếu đúng format `req-<8-hex>` (sai format thì sinh mới bằng `uuid4`), rồi `bind_contextvars(correlation_id=...)` và lưu vào `request.state`. ID được trả lại trong header `x-request-id`, body `correlation_id`, kèm `x-response-time-ms`; agent đưa ID vào trace metadata để nối log với trace.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, `user_id_hash` (SHA-256, 12 ký tự, không lưu user_id gốc), `session_id`, `feature`, `model`, `env`; log `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in/out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` được đăng ký trong structlog *trước* `JsonlFileProcessor` và `JSONRenderer`, nên payload/event đã được thay bằng `[REDACTED_*]` trước khi serialize. Pattern gồm email, điện thoại VN, CCCD, thẻ thanh toán và hộ chiếu VN.
- **Cách kiểm chứng kết quả:** chuyển log baseline ra `../logs-cp0-baseline.jsonl`, chạy lại `load_test.py` → `validate_logs.py` đạt 100/100 (0 thiếu field, 0 thiếu enrichment, 11 correlation ID, 0 PII leak). `pytest` 30 passed, gồm test CCCD, thẻ, hộ chiếu và `tests/test_correlation_id.py` (header, reuse/replace ID, log enrichment + scrub).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** trace nằm trong project `day13-k4-l3b-2A202602437` (region EU), được gửi bằng key của chính project này trong `.env`; mỗi trace có `correlation_id` trùng với một dòng trong `data/logs.jsonl` do `scripts/load_test.py` chạy trên máy tôi tạo ra, và `session_id` khớp `data/sample_queries.jsonl` (`s01`…`s10`).
- **Cấu trúc root/retrieval/generation observations:** trace `day13-agent-request` → root `lab-agent-run` (type `agent`, metadata prompt name/label/version, `correlation_id`) → hai child: `retrieval` (type `retriever`, `@observe` trên `retrieve()`, chỉ lưu `query_preview` đã scrub và `doc_count`) và `generation` (type `generation`, `@observe` trên `FakeLLM.generate()`, có `model`, `usage_details` input/output, `cost_details`, `completion_start_time` cho TTFT và prompt link qua `propagate_attributes(prompt=...)`). Không capture raw input/output (`capture_input=False, capture_output=False`).
- **Cách nối trace với log:** middleware sinh `correlation_id` (`req-<8-hex>`), dùng cho cả structured log và metadata của trace (`propagate_attributes(metadata={"correlation_id": ...})`). Từ một log line lấy `correlation_id`, trên Langfuse lọc Metadata `correlation_id` để mở đúng trace.
- **Prompt name:** `day13-chat` (text prompt, 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- **Version/label baseline:** version 1, labels `baseline` + `production`
- **Version/label candidate:** version 2 (thêm dòng "Answer concisely in at most 3 short bullet points."), label `candidate`
- **Trace ID của mỗi version:** cùng input "Explain how monitoring metrics logs and traces work together"
  - v1 / `baseline`: `ef0b3e5cf6f7b6162f67dd1584efbc0a` (`correlation_id=req-ba5e0009`, `prompt_version=1`, `tokens_in=44`)
  - v2 / `candidate`: `0f77a248038ace6929e5e108cf9721b5` (`correlation_id=req-ca0d1d02`, `prompt_version=2`, `tokens_in=56`)
  - Fake LLM trả cùng một câu trả lời nên hai version chỉ khác `prompt_version` và `tokens_in` (44 → 56 do v2 thêm một dòng hướng dẫn).
- **Cách promote và rollback `production`:** app chỉ hỏi Langfuse prompt `day13-chat` theo label trong `LANGFUSE_PROMPT_LABEL`, nên đổi version không cần sửa code, chỉ dời label rồi restart API (prompt được cache 60 giây).
  - Promote: gắn `production` cho v2 (label tự rời khỏi v1) → request kiểm tra `req-9a0de002`, trace `c731383f8d24a90dc59759f95abd23be`: `prompt_label=production`, `prompt_version=2`.
  - Rollback: gắn lại `production` cho v1 (v2 chỉ còn `candidate`, `latest`) → request kiểm tra `req-b0bac001`, trace `64c0cbdc1183819593e78be863b23e3b`: `prompt_label=production`, `prompt_version=1`, `tokens_in=44`.
  - Evidence: `evidence/10a-prompt-after-promote.png` (production ở v2) và `evidence/10b-prompt-after-rollback.png` (production về v1).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `scripts/dashboard.py` đọc `data/logs.jsonl` và chính `config/dashboard.yaml` (tên panel, unit, threshold, time range 60 phút, refresh 30 giây), chạy bằng `python scripts/dashboard.py` → http://127.0.0.1:8050. Sáu panel: Latency (P50/P95/P99 + TTFT P95, threshold P95 ≤ 3000 ms), Traffic (request/phút, ≥ 1), Errors (error rate % ≤ 2, breakdown `error_type`, retrieval success % tính trên mọi event có `tool_success`), Cost (USD/phút + cumulative, total ≤ 2.5), Tokens (tokens_in/out theo phút + cumulative, ≤ 50,000), Quality (mean ≥ 0.75). Mỗi panel có badge OK/BREACH so với threshold.
- **SLO và lý do chọn:** `fast_successful_requests`: 99.5% request có `response_sent` với `latency_ms ≤ 3000` trong 28 ngày. Baseline CP0 P95 = 1405 ms, nên ngưỡng 3000 ms còn khoảng 2 lần headroom, tránh báo động giả nhưng bắt được ngay khi một bước chậm thêm vài giây. Request lỗi không có `response_sent` nên cũng là bad event.
- **Cách tính error budget:** `allowed_bad = floor(total × (100 − 99.5) / 100)`. 10,000 request → 50; traffic tối thiểu 1 request/phút trong 28 ngày = 40,320 request → 201; một buổi lab ~200 request → 1. Tiêu > 50% budget thì ưu tiên điều tra/rollback thay vì release mới.
- **Ba alert và runbook tương ứng:** (`config/alert_rules.yaml`, runbook trong `docs/alerts.md`, Slack `#k4-l3b-alerts`, owner `student-2A202602437`)
  1. `ChatLatencyP95High` (critical, 5m): P95 latency > 3000 ms → runbook `#alert-1`.
  2. `ChatErrorRateHigh` (critical, 5m): error rate > 2% hoặc retrieval success < 90% → runbook `#alert-2`.
  3. `ChatCostPerRequestSpike` (warning, 10m): cost trung bình > 0.004 USD/request (2× baseline) hoặc > 2.5 USD/24h → runbook `#alert-3`.

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, seed 1312, feature bị ảnh hưởng `monitoring`, ngưỡng `latency_threshold_ms = 2000`). Chạy đúng lệnh `python scripts/inject_incident.py` rồi `python scripts/load_test.py --challenge --concurrency 5`.
- **Khoảng thời gian điều tra:** 2026-09-30 04:31–04:40 UTC (11:31–11:40 giờ VN). Mốc trước incident 04:31:35–04:32:56; bật incident 04:33:04; tắt incident 04:38:57; kiểm tra hồi phục 04:38:57–04:40:05. Log trước đó được chuyển ra `../logs-cp2.jsonl` để cửa sổ điều tra chỉ chứa workload challenge.
- **Triệu chứng từ metrics:** (`evidence/12-incident-metric.png`, dashboard phóng to 10 phút có đường ngưỡng challenge 2000 ms)

  | Giai đoạn | n | Latency P50 | Latency P95 | > 2000 ms | TTFT P95 | Error rate | tokens_out TB | Quality |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|
  | Trước incident | 15 | 154 ms | 1204 ms | 0/15 | 51 ms | 0% | 128 | 0.84 |
  | Trong incident | 20 | **2655 ms** | **2658 ms** | **20/20** | 51 ms | 0% | 127 | 0.84 |
  | Sau khi tắt | 15 | 153 ms | 2001 ms | 1/15 | 51 ms | 0% | – | – |

  Chỉ latency tăng, đều khoảng +2.5 s trên mọi request của feature `monitoring`; HTTP vẫn 200, error rate, token, cost và quality không đổi, TTFT không đổi nên phần chậm nằm trước bước sinh token. P95 2658 ms chưa vượt ngưỡng SLO chung 3000 ms (panel latency vẫn "OK") nhưng vượt ngưỡng challenge 2000 ms ở 100% request. (Request duy nhất > 2000 ms sau khi tắt là request đầu tiên phải tải lại prompt khi cache 60 s hết hạn, không liên quan retrieval.)
- **Log line và correlation ID liên quan:** (`evidence/13-incident-log.png`) lọc `response_sent` có `feature == "monitoring"` và `latency_ms > 2000` → 20 request, chọn `req-8adee3f6`:
  `{"event": "response_sent", "correlation_id": "req-8adee3f6", "session_id": "k4-l3b-challenge-s01", "feature": "monitoring", "latency_ms": 2653, "ttft_ms": 50, "tokens_out": 98, "tool_name": "retrieval", "tool_success": true, "ts": "2026-09-30T04:33:10.723853Z", ...}`
- **Trace ID và span gây ảnh hưởng:** (`evidence/14-incident-trace.png`) trace `63af7498e000be5d874e583502802f73` (metadata `correlation_id = req-8adee3f6`): `lab-agent-run` 2.653 s = **`retrieval` 2.501 s** (~94%) + `generation` 0.152 s. So với trace trước incident `6942bf851ed7596f508e9850c3a6fceb` (`req-a167d8f2`): `retrieval` 0.001 s, `generation` 0.152 s. Trên Langfuse, cả 20 span `retrieval` trong incident đều 2.501–2.503 s (trước đó 0.000–0.002 s), còn `generation` giữ 0.152–0.154 s.
- **Root cause:** bước retrieval (vector store / RAG) chậm thêm cố định khoảng 2.5 s mỗi lần gọi (incident `rag_slow`), làm mọi request `monitoring` vượt ngưỡng 2000 ms dù vẫn trả HTTP 200. Metric (latency tăng, TTFT/token/lỗi không đổi), log (`latency_ms` ≈ 2655 với `ttft_ms` 50) và trace (span `retrieval` 2.5 s, `generation` không đổi) cùng chỉ về một nguyên nhân. Ngoài ra endpoint `async def chat` gọi `agent.run()` đồng bộ nên thời gian chờ retrieval chặn event loop: các request đồng thời bị xếp hàng (log cách nhau ~2.66 s), phía client thấy 8–13 s dù mỗi request ở server chỉ ~2.65 s.
- **Fix action:** khôi phục dependency retrieval (`python scripts/inject_incident.py --disable`), chạy lại cùng workload challenge: P50 về 153 ms, `retrieval` về ~0.001 s, 14/15 request < 2000 ms (request còn lại là lần tải lại prompt).
- **Preventive measure:**
  1. Alert theo ngưỡng của feature: thêm điều kiện `p95(latency_ms{feature="monitoring"}) > 2000` trong 5 phút, vì SLO chung 3000 ms không bắt được incident này; và alert trực tiếp trên thời lượng span `retrieval` (ví dụ P95 > 500 ms) để báo đúng thành phần trước khi user thấy chậm.
  2. Guardrail cho retrieval: đặt timeout (ví dụ 1 s) và fallback (trả lời không có context hoặc dùng cache kết quả) thay vì chờ vô hạn.
  3. Không chặn event loop: chạy `agent.run()` trong threadpool (`run_in_threadpool` hoặc khai báo endpoint `def`) để một dependency chậm không làm các request khác xếp hàng.
  4. Runbook Alert 1 (`docs/alerts.md#alert-1`) đã mô tả đúng luồng Metrics → Logs → Traces dùng trong lần điều tra này.

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** trace không capture input/output thô (`capture_input=False, capture_output=False`), chỉ lưu preview đã qua `scrub_text` và metadata an toàn; prompt version được nối vào generation bằng `propagate_attributes(prompt=...)` thay vì gửi nội dung prompt đã điền câu hỏi. Lý do: câu hỏi người dùng có thể chứa email/SĐT/CCCD/thẻ, và trace được gửi ra dịch vụ ngoài (Langfuse Cloud) nên phải an toàn như log; trong khi đó vẫn đủ thông tin để debug (thời lượng span, model, usage, cost, prompt name/version, `correlation_id`). Quyết định thứ hai là dựng dashboard bằng `scripts/dashboard.py` đọc trực tiếp `config/dashboard.yaml`: tên panel, đơn vị, threshold và time range lấy từ contract nên không lệch khỏi contract, và không cần cài thêm thư viện vào venv của API.
- **Một lỗi/blocker đã gặp:** sau khi điền key, API vẫn trả HTTP 200 nhưng terminal báo `401 Unauthorized` khi tải prompt và `Failed to export spans … 401`, nên không có trace nào lên Langfuse. Sau khi sửa `.env` lỗi vẫn còn.
- **Cách tìm nguyên nhân và xử lý:** gọi `GET /api/public/projects` với cùng key lên từng region: chỉ `https://cloud.langfuse.com` (EU) trả OK với project `day13-k4-l3b-2A202602437`, còn `.env` đang trỏ `us.cloud.langfuse.com` → sửa `LANGFUSE_BASE_URL`. Lỗi còn lại vì `netstat` cho thấy hai tiến trình uvicorn cùng giữ port 8000, một tiến trình khởi động trước khi sửa `.env`; tắt cả hai rồi chạy lại một API thì `/health` trả `tracing_enabled: true` và trace xuất hiện. Blocker thứ hai là mạng tới Langfuse chập chờn (timeout, lỗi DNS): một số batch span bị mất và vài request chậm 6–12 s do tải prompt; tôi xác nhận bằng trace (khoảng trống trước `generation`, TTFT không đổi), chạy lại request trong process riêng có `flush()` và `LANGFUSE_TIMEOUT` dài hơn, và kiểm tra số trace bằng Observations API.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics trả lời "có vấn đề không, từ lúc nào, mức độ ra sao" trên toàn hệ thống (trong challenge: P50 154 → 2655 ms, 20/20 request > 2000 ms, lỗi/token/TTFT không đổi). Logs trả lời "request cụ thể nào bị ảnh hưởng" (lọc `latency_ms > 2000` → `req-8adee3f6` với `ttft_ms` 50). Traces trả lời "chậm ở bước nào bên trong request" (trace cùng `correlation_id`: `retrieval` 2.50 s / 2.65 s). `correlation_id` là khóa nối log với trace; chỉ kết luận root cause khi cả ba lớp cùng chỉ về một nguyên nhân.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là một phần của "code" nhưng đổi được mà không deploy; ghi `prompt_name/label/version` vào trace cho biết mỗi request dùng version nào (v1 `tokens_in` 44, v2 56), và rollback chỉ là dời label `production` về v1 rồi restart, không sửa code. Token/cost là tín hiệu riêng của LLM: một prompt dài hơn hoặc câu trả lời dài bất thường làm chi phí tăng mà HTTP vẫn 200 (Alert 3). SLO + error budget biến "chậm/lỗi" thành con số có thể ra quyết định: còn budget thì được release, tiêu > 50% thì ưu tiên điều tra/rollback.
- **Điều quan trọng nhất đã học:** HTTP 200 không có nghĩa là hệ thống ổn. Trong challenge toàn bộ request vẫn 200 nhưng mỗi request chậm thêm 2.5 s; chỉ nhờ latency metric, log có `correlation_id` và trace có span riêng cho retrieval mới khoanh được đúng bước gây lỗi thay vì đoán. Tôi cũng thấy ngưỡng SLO chung (3000 ms) không bắt được sự cố này, nên alert cần theo ngưỡng của từng feature/span.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - Alert mới được định nghĩa trong `config/alert_rules.yaml` và runbook, chưa nối vào hệ thống gửi Slack thật; dashboard là script local, không lưu lịch sử ngoài `data/logs.jsonl`.
  - Preventive measure "không chặn event loop" (chạy `agent.run()` trong threadpool) và timeout/fallback cho retrieval mới được đề xuất, chưa triển khai, để giữ đúng hành vi của starter khi chấm challenge.
  - Do mạng không ổn định, một phần trace của load test bị mất (vẫn có > 60 trace đủ cây); một số request CP2 có latency cao do tải prompt chậm, làm P95 cửa sổ CP2 vượt 3000 ms.
  - Tạo prompt v2 và dời label promote/rollback được thực hiện qua Langfuse Public API (kết quả giống thao tác UI); ảnh 08 và 14 chụp từ link chia sẻ public tạm thời của hai trace đó; public key trong ảnh đã được che thành `pk-lf-[REDACTED]` (không thay đổi số liệu nào).

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối (01–03 chụp lại trên code cuối: 37 passed, 100/100, 6/6).
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối (16/16 đường dẫn trong báo cáo tồn tại).
- [x] Incident evidence nối đúng metric → log → trace (`12` → `13` `req-8adee3f6` → `14` trace `63af7498…`).
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác (`.env`, `data/logs.jsonl`, `config/challenge.json` không được commit).
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
