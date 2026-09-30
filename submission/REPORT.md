# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Vũ Đức Thiện
- **MSSV:** 2A202602437
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/vuthien3002-sys/K4-L3B-Day13-VuDucThien-2A202602437-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:**
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
| `validate_logs.py` | 30/100 (thiếu correlation ID, thiếu enrichment) | 100/100 (413 records, 196 correlation ID) | CP1: middleware + bind context + `scrub_event` |
| `validate_dashboard.py` | 6/6 panel hợp lệ | 6/6 panel hợp lệ | Dashboard runtime: `scripts/dashboard.py` |
| `pytest` | 22 passed | 36 passed | Thêm test PII, correlation ID, child observation, dashboard |
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

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
