# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `ChatLatencyP95High`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` trong `config/slo.yaml` (99.5% request có `response_sent` với `latency_ms <= 3000`, cửa sổ 28 ngày); panel **Latency percentiles and TTFT**.
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms) > 3000` liên tục trong 5 phút. Baseline P95 = 1405 ms nên vượt 3000 ms là bất thường thật, không phải dao động.
- Ảnh hưởng tới người dùng: người dùng chờ hơn 3 giây mới nhận được câu trả lời; mỗi request chậm tiêu vào error budget (0.5%).
- Ba bước kiểm tra đầu tiên:
  1. **Metrics**: mở dashboard (`python scripts/dashboard.py`), xem panel Latency: P95/P99 tăng từ lúc nào, TTFT P95 có tăng theo không. TTFT không đổi mà tổng latency tăng thì phần chậm nằm trước hoặc ngoài lúc sinh token (retrieval, tải prompt).
  2. **Logs**: lấy các request chậm trong khoảng đó và một `correlation_id` đại diện:
     `Get-Content data\logs.jsonl | ConvertFrom-Json | Where-Object { $_.event -eq "response_sent" -and $_.latency_ms -gt 3000 } | Select-Object ts, correlation_id, feature, latency_ms, ttft_ms`
  3. **Traces**: trên Langfuse → Tracing, lọc Metadata `correlation_id = <id>`, mở trace `day13-agent-request` và so thời lượng các span `retrieval` và `generation` trong `lab-agent-run` để xác định bước chậm.
- Mitigation tạm thời: nếu `retrieval` chậm, khôi phục/khởi động lại dependency retrieval hoặc tắt practice scenario (`python scripts/inject_incident.py --scenario <name> --disable`); nếu `generation` chậm sau khi đổi prompt, rollback label `production` về version trước; giảm tải (concurrency) khi demo.
- Owner: `student-2A202602437`

## Alert 2

- Tên: `ChatErrorRateHigh`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (request lỗi không có `response_sent` nên là bad event); guardrails `error_rate_pct_max: 2` và `retrieval_success_rate_pct_min: 90`; panel **Error rate and retrieval success**.
- Điều kiện và thời gian duy trì: error rate `count(request_failed) / count(request_received) * 100 > 2` **hoặc** retrieval success (`tool_success == true` trên mọi event có `tool_success`) `< 90%`, kéo dài 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 thay vì câu trả lời; error budget bị tiêu rất nhanh.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics**: trên panel Errors xem error rate, retrieval success và breakdown theo `error_type` (lỗi dồn vào một loại hay rải rác).
  2. **Logs**: lọc log lỗi để lấy `error_type`, `tool_name`, `payload.detail` và `correlation_id`:
     `Get-Content data\logs.jsonl | ConvertFrom-Json | Where-Object { $_.event -eq "request_failed" } | Select-Object ts, correlation_id, error_type, tool_name, @{n="detail";e={$_.payload.detail}}`
  3. **Traces**: mở trace cùng `correlation_id` trên Langfuse; observation bị lỗi có level `ERROR` và status message chứa exception, cho biết lỗi xảy ra ở `retrieval` hay `generation`.
- Mitigation tạm thời: nếu lỗi nằm ở `retrieval` (ví dụ timeout vector store), khôi phục dependency hoặc tắt practice scenario; nếu lỗi bắt đầu ngay sau khi đổi prompt/cấu hình, rollback thay đổi đó; theo dõi error rate trở về dưới 2%.
- Owner: `student-2A202602437`

## Alert 3

- Tên: `ChatCostPerRequestSpike`
- Severity: `warning`
- Duration: `10m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5` trong `config/slo.yaml`; panel **Cost over time** và **Input and output tokens**.
- Điều kiện và thời gian duy trì: chi phí trung bình `avg(response_sent.cost_usd) > 0.004` USD/request (gấp đôi baseline ~0.002) **hoặc** tổng chi phí 24 giờ `> 2.5` USD, kéo dài 10 phút. Dùng 10 phút vì cost ít khẩn cấp hơn lỗi/chậm và cần loại trừ vài câu trả lời dài đơn lẻ.
- Ảnh hưởng tới người dùng: câu trả lời dài bất thường (khó đọc, chậm hơn) và chi phí vận hành tăng, có nguy cơ vượt ngân sách ngày.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics**: so panel Cost với panel Tokens: cost tăng đi cùng `tokens_out` tăng (model trả lời dài) hay `tokens_in` tăng (prompt/context dài).
  2. **Logs**: lấy các request đắt nhất cùng `correlation_id`:
     `Get-Content data\logs.jsonl | ConvertFrom-Json | Where-Object { $_.event -eq "response_sent" } | Sort-Object cost_usd -Descending | Select-Object -First 5 ts, correlation_id, feature, tokens_in, tokens_out, cost_usd`
  3. **Traces**: mở trace cùng `correlation_id`, xem observation `generation`: `usage` input/output, `cost` và **prompt name/version** đang dùng để biết cost tăng có trùng lúc đổi prompt version không.
- Mitigation tạm thời: nếu tăng sau khi promote prompt mới, rollback label `production` về version trước; giới hạn độ dài câu trả lời (max output tokens); tắt practice scenario nếu đang chạy.
- Owner: `student-2A202602437`
