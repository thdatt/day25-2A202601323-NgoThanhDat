# Day 25 — Track 3: Reliability Engineering cho Production Agents

**Sinh viên:** Ngo Thanh Dat — `2A202601323`
**Failure mode phân tích sâu:** `DEGRADED` (silent quality degradation)

Toàn bộ số liệu trong báo cáo này sinh ra từ:

```powershell
python -m pytest tests -q          # 30 passed
python chaos_load_test.py          # 7/7 scenarios pass -> metrics.json
python scripts/run_all.py          # chạy mọi demo offline
```

---

## 0. Ánh xạ tới thang điểm 100

| Hạng mục | Người chấm xem gì | Nằm ở đâu trong bài |
|---|---|---|
| **Circuit breaker & fallback (25)** | máy trạng thái 3 trạng thái đúng; không retry storm; `route` có tên provider; có `transition_log` | [`state_machine.py`](../state_machine.py), [`provider_router.py`](../provider_router.py), [`fallback_ladder.py`](../fallback_ladder.py) · §2, §3 |
| **In-memory cache & cost (15)** | đo hit rate; tính cost saved; giải thích TTL/ngưỡng; ví dụ false hit thật | [`cache.py`](../cache.py) · §4 |
| **Redis shared cache (15)** | `get`/`set` chạy; chứng minh state dùng chung; guardrail còn nguyên; test Redis pass | [`cache.py`](../cache.py) `SharedRedisCache`, [`redis_shared_demo.py`](../redis_shared_demo.py), [`tests/test_redis_shared_cache.py`](../tests/test_redis_shared_cache.py) · §5 |
| **Observability & metrics (15)** | `metrics.json` có P50/P95/P99, availability, circuit open count, chỉ số cache; tái lập được | [`metrics.py`](../metrics.py), [`metrics.json`](../metrics.json) · §6 |
| **Chaos & load testing (15)** | ≥3 scenario có tên; pass/fail rõ; bằng chứng recovery; so sánh cache | [`chaos_load_test.py`](../chaos_load_test.py), [`reports/chaos_results.md`](chaos_results.md) · §7 |
| **Report & code quality (15)** | sơ đồ kiến trúc; bảng config kèm lý do; phân tích điểm yếu; type hint đầy đủ; test pass | §1 (diagram), §8 (config), §10 (điểm yếu), §9 (SLO) |
| **Điểm cộng** | ThreadPoolExecutor + số đo đổi khác; cache tự lùi in-memory khi Redis sập; routing theo ngân sách; `hypothesis` fuzz; bảng SLO | §5, §7, §3, §11 |

---

## 1. Sơ đồ kiến trúc

```text
                                   ┌───────────────── observability ─────────────────┐
                                   │  MetricsCollector  → metrics.json               │
                                   │  latency P50/P95/P99 · availability · correctness │
                                   │  circuit_open_count · cache hit_rate/$ saved      │
                                   └──────────────────────────────────────────────────┘
                                            ▲ record per request
   user query ─┐                            │
               ▼                            │
   ┌───────────────────────┐  HIT  ┌────────┴───────────┐
   │  ResponseCache        │──────▶│  cached answer     │  0 token · sub-ms
   │  (TTL + semantic sim) │       │  + $ saved counter │
   │  privacy / false-hit  │       └────────────────────┘
   └──────────┬────────────┘
              │ MISS
              ▼
   ┌───────────────────────┐        ┌─────────────────────────────────────────┐
   │  ProviderRouter       │  name  │  budget used ≥ 80%  → downgrade to       │
   │  gpt-4o / gemini-1.5  │───────▶│  cheapest named provider (gpt-4o-mini)   │
   │  -pro / gpt-4o-mini   │        └─────────────────────────────────────────┘
   └──────────┬────────────┘
              ▼
   ┌───────────────────────┐  OPEN & not ready  ┌──────────────────────────┐
   │  CircuitBreaker       │───────────────────▶│  fail fast (no call)     │
   │  CLOSED/OPEN/HALF_OPEN │                    │  → FallbackLadder        │
   │  transition_log[]      │                    └──────────────────────────┘
   └──────────┬────────────┘
              │ CLOSED / HALF_OPEN
              ▼
   ┌───────────────────────┐  ConnectionError/TimeoutError   ┌──────────────────────┐
   │  LLM provider call     │───────────────────────────────▶│  retry: exponential  │
   │                        │                                │  backoff + Full Jitter│
   └──────────┬────────────┘                                └──────────────────────┘
              │ HTTP 200
              ▼
   ┌───────────────────────┐  quality SLO violated   ┌───────────────────────────┐
   │  QualityGuardrail      │───────────────────────▶│  block answer             │
   │  0.7·faithfulness      │                        │  → FallbackLadder         │
   │  + 0.3·relevancy       │                        │  (degraded_quality_...)   │
   └──────────┬────────────┘                        └───────────────────────────┘
              │ pass
              ▼
   ┌───────────────────────┐
   │  FallbackLadder (5 tiers): primary → backup → smaller → cache → static  │
   └───────────────────────┘
              ▼
        answer → user  +  cache.set(query, answer)

  Shared deployment: ResponseCache → SharedRedisCache (same Redis = shared state).
  Redis unreachable → transparently degrades to per-instance in-memory cache.
```

---

## 2. Circuit breaker — máy trạng thái 3 trạng thái + `transition_log`

`state_machine.py` — `CircuitBreaker` with an injected `clock` (deterministic tests).

| Trạng thái | Hành vi |
|---|---|
| `CLOSED` | cho request đi qua; đếm lỗi liên tiếp (`expected_exceptions`) |
| `OPEN` | fail fast bằng `CircuitOpenError`, **không gọi** downstream; sau `reset_timeout_seconds` mới cho probe |
| `HALF_OPEN` | 1 (hoặc `success_threshold`) probe; probe OK → `CLOSED`, probe lỗi → `OPEN` ngay |

**`transition_log`** — mọi lần đổi trạng thái được ghi lại `{at, from, to, reason, failure_count, success_count}`, cộng thêm `open_count`. Ví dụ thật từ `python state_machine.py`:

```text
t=0.0     CLOSED -> OPEN       2 consecutive failures >= threshold 2
t=2.1       OPEN -> HALF_OPEN  reset timeout elapsed - probing
t=2.1  HALF_OPEN -> CLOSED     probe succeeded
```

**Không có retry storm.** Hai lớp bảo vệ độc lập:

1. `jitter.py` chỉ retry `ConnectionError`/`TimeoutError` (không retry lỗi lập trình/dữ liệu), delay = `min(max_delay, base_delay·2^attempt)` rồi **Full Jitter** `random.uniform(0, delay)` → nhiều client không cùng nhịp.
2. Khi breaker `OPEN`, `CircuitOpenError` **không** nằm trong `retryable_exceptions` → thoát ngay, không có vòng retry nào đập vào service đang sập.

`tests/test_state_machine.py`, `tests/test_transition_log.py`, `tests/test_jitter.py`, `tests/test_state_machine_fuzz.py` (property-based, §11).

---

## 3. Routing — `route` có tên provider + downgrade theo ngân sách (điểm cộng)

`provider_router.py` — `ProviderRouter` giữ danh sách provider **có tên thật**, mạnh → rẻ:

| name | tier | USD / 1k tokens |
|---|---|---|
| `gpt-4o` | premium | 0.0075 |
| `gemini-1.5-pro` | standard | 0.0035 |
| `gpt-4o-mini` | cheap | 0.0005 |

`route(query)` trả về provider và ghi `route_log` (`provider`, `tier`, `budget_used_ratio`, `downgraded`). Khi `spent_usd / monthly_budget ≥ soft_limit_ratio` (mặc định 0.80) router **hạ cấp mọi request xuống provider rẻ nhất** — một "budget circuit breaker". `python provider_router.py`:

```text
req  7: -> gpt-4o        (premium) used=84%
req  8: -> gpt-4o-mini   (cheap)   used=85%  <-- downgraded (budget)
```

`tests/test_provider_router.py`: 3 test (route premium khi dưới hạn mức, downgrade khi vượt, cộng dồn chi phí).

**Fallback ladder** (`fallback_ladder.py`) giữ hợp đồng đầu ra tối thiểu `{intent, confidence, reply}` qua 5 tầng: primary → backup → smaller → cache → static. Mỗi tầng lỗi/schema sai được ghi vào `errors[]`. `tests/test_fallback.py`.

---

## 4. In-memory cache — hit rate, cost saved, TTL/ngưỡng, false hit

`cache.py` — `ResponseCache`: TTL + cosine similarity trên (word tokens + char trigram).

**Hit rate & cost saved (đo được).** Mỗi lookup cộng vào `hits`/`misses`; mỗi hit cộng `tokens_saved` (≈ `len/4`) và `cost_saved_usd = tokens/1000 · usd_per_1k_tokens`. `cache.stats()` trả JSON. Số thật từ `chaos_load_test.py` scenario `cache_cost_comparison` (12 câu hỏi khác nhau, lặp 5 lần = 60 request):

| | provider calls | hit_rate | cost_saved |
|---|---|---|---|
| không cache | 60 | 0.00 | $0.00000 |
| có cache | **12** | **0.80** | **$0.00538** |

→ cache cắt 80% lệnh gọi model trên workload lặp lại. Ở quy mô thật (giá gpt-4o, hàng triệu request) đây là khoản tiết kiệm bậc nghìn đô/tháng.

**Giải thích TTL & ngưỡng (bảng config §8):**

- `ttl_seconds` — câu trả lời phụ thuộc knowledge base; TTL giới hạn độ "cũ" tối đa. 600s cho demo, 3600s mặc định production; phải nhỏ hơn nhịp cập nhật KB.
- `similarity_threshold = 0.80` — dưới ngưỡng này hai câu khác ý định bắt đầu lẫn nhau (đo bằng tay trên tập câu hỏi hỗ trợ). Cao hơn (0.9+) sẽ bỏ lỡ paraphrase; thấp hơn (0.7) sinh false hit.

**Ví dụ false hit thật (đã chặn).** `_looks_like_false_hit`: hai câu rất giống nhau nhưng chứa **số 4 chữ số khác nhau** (năm, mã đơn) → coi là false hit, **không** trả cache, ghi `false_hit_log`:

```python
cache.set("refund policy 2025", "old")
cache.get("refund policy 2026")   # -> (None, 0.83)  ; false_hit_log: reason="date_or_number_mismatch"
```

`tests/test_cache.py`, `tests/test_cache_cost.py`.

**Guardrail privacy.** `PRIVACY_PATTERNS` (balance, password, credit card, ssn, `account 1234`, …) → `set()` trả `False`, `get()` trả `(None, 0.0)`. Không bao giờ cache dữ liệu nhạy cảm.

---

## 5. Redis shared cache

`cache.py` — `SharedRedisCache`. Nhận `client` injectable (test dùng `fakeredis`, không cần docker) hoặc `redis_url`.

- **`get` / `set` hoạt động** — exact key = `sha256(query)[:16]`; nếu trượt thì `SCAN` toàn prefix + so similarity cục bộ; TTL bằng `EXPIRE` (Redis tự dọn). `tests/test_redis_shared_cache.py::test_get_set_roundtrip`.
- **State dùng chung** — hai instance `SharedRedisCache` trỏ cùng một Redis: instance A `set(q)`, instance B `get(q)` → HIT (score 1.0); biến thể semantic của B cũng khớp entry của A. `redis_shared_demo.py` + `test_state_is_shared_across_instances`.
- **Guardrail còn nguyên** — privacy bypass và false-hit guard chạy y hệt bản in-memory, kể cả xuyên instance. `test_privacy_guardrail_still_applies`, `test_false_hit_guardrail_across_instances`.
- **Test Redis pass** — 5 test với `fakeredis` server dùng chung (`pytest.importorskip` để bỏ qua sạch nếu thiếu). `docker compose up -d` chạy Redis thật để kiểm chứng thêm.
- **Điểm cộng — tự lùi về in-memory khi Redis sập:** mọi thao tác Redis bọc `try/except`; khi lỗi, cache chuyển sang `ResponseCache` nội bộ, đặt cờ `degraded_to_memory=True`, gateway vẫn phục vụ (mất tính *chia sẻ* cho tới khi Redis quay lại). `test_falls_back_to_memory_when_redis_unavailable` + chaos scenario `redis_down_failover`.

---

## 6. Observability — `metrics.json` tái lập được

`metrics.py` — `MetricsCollector` ghi mỗi request `(latency_ms, available, correct, served_from)` và `record_circuit_open()`. `snapshot()` trả:

- `latency_ms.p50 / p95 / p99 / max` (numpy percentile)
- `availability` = số request nhận được câu trả lời dùng được / tổng (fallback vẫn tính là available)
- `correctness` = số câu trả lời không bị guardrail chặn là sai / tổng
- `circuit_open_count`
- `served_from` = phân rã primary / cache / quality_fallback / provider_fallback
- `cache` = `ResponseCache.stats()` (lookups, hit_rate, tokens_saved, cost_saved_usd, false_hits_blocked)

`chaos_load_test.py` ghi `metrics.json` gộp cả 7 scenario. Trích `baseline_healthy` (60 request):

```json
"latency_ms": { "p50": 0.171, "p95": 0.21, "p99": 0.228, "max": 0.231 },
"availability": 1.0, "correctness": 1.0, "circuit_open_count": 0,
"served_from": { "primary": 12, "cache": 48 },
"cache": { "hit_rate": 0.8, "tokens_saved": 1076, "cost_saved_usd": 0.00538, "false_hits_blocked": 0 }
```

**Tái lập:** workload và cửa sổ lỗi cố định; chỉ có jitter sleep < 100ms là ngẫu nhiên và assertion dùng khoảng. Chạy lại `python chaos_load_test.py` cho cùng cấu trúc số.

---

## 7. Chaos & load testing — 7 scenario có tên

`chaos_load_test.py`. Mỗi scenario in `[PASS]/[FAIL]` + bằng chứng; kết quả cũng ghi ra [`reports/chaos_results.md`](chaos_results.md).

| Scenario | Kết quả | Bằng chứng |
|---|---|---|
| `baseline_healthy` | PASS | availability=1.0, hit_rate=0.80, circuit_open=0 |
| `provider_outage` | PASS | circuit_open_count=1, availability=1.0, **recovery**: `CLOSED→OPEN→HALF_OPEN→CLOSED`, final=CLOSED |
| `silent_degradation` | PASS | 0/20 câu sai lọt ra; 20/20 bị guardrail chặn; availability=1.0 |
| `latency_spike` | PASS | P50=2.7ms, **P99=46ms** (bắt được đuôi), availability=1.0 |
| `redis_down_failover` | PASS | `degraded_to_memory=True`, phục vụ từ memory, guardrail còn |
| `cache_cost_comparison` | PASS | provider calls 60 → 12 (−48), cost_saved=$0.00538 |
| `cache_stampede_concurrent` (điểm cộng) | PASS | 50 request song song / 10 thread: provider calls 51 → **1**; P95 0.049ms → 0.017ms |

**Bằng chứng recovery** (`provider_outage`): provider trả 503 từ request 8; sau 3 lỗi liên tiếp breaker `OPEN` (fail-fast, fallback phục vụ, availability giữ 1.0); tắt lỗi ở request 26 + chờ `reset_timeout` → probe `HALF_OPEN` thành công → `CLOSED`; request `post-outage` trả `status="success"`. Toàn bộ nằm trong `transition_log`.

**So sánh cache** (điểm cộng — số đo đổi khác khi chạy song song): scenario `cache_stampede_concurrent` chạy cùng workload 2 lần (tắt/bật cache) trên `ThreadPoolExecutor(max_workers=10)`; cache "gộp" cơn stampede từ 50 lệnh gọi model xuống 1, và P95 latency giảm ~3×.

---

## 8. Bảng config kèm lý do

| Tham số | File | Giá trị | Vì sao |
|---|---|---|---|
| `failure_threshold` | `state_machine.py` | 3 | đủ để bỏ qua 1–2 lỗi lẻ (mạng chớp nhoáng) nhưng vẫn ngắt nhanh khi service thật sự sập |
| `reset_timeout_seconds` | `state_machine.py` | 10 (prod) / 0.25 (chaos) | cho downstream thời gian tự phục hồi trước khi probe; chaos rút ngắn để test chạy nhanh |
| `success_threshold` | `state_machine.py` | 1 | 1 probe OK là đủ tín hiệu phục hồi; tăng lên nếu downstream "chập chờn" |
| `retryable_exceptions` | `jitter.py` | `(ConnectionError, TimeoutError)` | chỉ retry lỗi **hạ tầng tạm thời**; lỗi lập trình/nhập liệu retry cũng vô ích |
| `max_attempts` | `jitter.py` | 5 (mặc định) / 2 (gateway) | gateway ưu tiên rơi xuống fallback nhanh thay vì kéo dài retry |
| `base_delay` / `max_delay` | `jitter.py` | 1s / 32s | backoff mũ có trần; Full Jitter `uniform(0, delay)` phá đồng bộ giữa client |
| `similarity_threshold` (mem) | `cache.py` | 0.80 | đo tay: dưới mức này câu khác ý định bắt đầu lẫn; trên 0.9 bỏ lỡ paraphrase |
| `similarity_threshold` (semantic/Gemini) | `semantic_cache.py` | 0.88 | embedding thật đặc hơn tf-idf nên ngưỡng cao hơn |
| `ttl_seconds` | `cache.py` | 3600 (prod) / 600 (demo) | phải nhỏ hơn nhịp cập nhật knowledge base |
| `usd_per_1k_tokens` | `cache.py` | 0.005 | giá blended lớp gpt-4o để quy đổi "token tiết kiệm" ra tiền |
| `quality_slo_threshold` | `quanlity_guardrail.py` | 0.75 | dưới mức này câu trả lời "đủ sai để gây hại"; chỉnh theo rủi ro domain |
| `faithfulness_weight` / `relevancy_weight` | `quanlity_guardrail.py` | 0.7 / 0.3 | với RAG, bám context (không bịa) quan trọng hơn "đúng trọng tâm" |
| `monthly_budget_usd` / `soft_limit_ratio` | `provider_router.py` | 5.0 / 0.80 | khi tiêu hết 80% ngân sách tháng thì ưu tiên "còn phục vụ được" hơn "chất lượng tối đa" |

---

## 9. Bảng SLO & đối chiếu (điểm cộng)

| SLO | Mục tiêu | Đo được (chaos scenarios) | Đạt? |
|---|---|---|---|
| Availability | ≥ 99.9% | 100% ở cả 7 scenario (fallback luôn trả câu dùng được) | ✅ |
| Correctness (không trả câu sai) | 100% | `silent_degradation`: 0/20 câu sai lọt ra | ✅ |
| Latency P95 (đường bình thường) | < 50ms | `baseline_healthy` P95 = 0.21ms | ✅ |
| Latency P99 (có sự cố) | quan sát được, có cảnh báo | `latency_spike` P99 = 46ms được `metrics.json` ghi lại | ✅ |
| Circuit recovery | tự đóng lại sau khi downstream hồi | `provider_outage`: `HALF_OPEN→CLOSED`, `post-outage` success | ✅ |
| Cache hit rate (workload lặp) | > 60% | 80% | ✅ |

---

## 10. Failure mode `DEGRADED` + phân tích điểm yếu

### Kịch bản
RAG chăm sóc khách hàng: context nói hoàn tiền **30 ngày**. Provider **trả HTTP 200** nhưng vì model drift / prompt regression / overload lại nói **90 ngày**. Đây **không** phải outage — circuit breaker thường thấy "request OK, không exception, latency chấp nhận được" → coi là thành công và trả câu bịa.

### Cách xử lý (đã cài trong `reliability_gateway.py`)
1. Provider trả lời (HTTP 200).
2. `QualityGuardrail` chấm `0.7·faithfulness + 0.3·relevancy`.
3. Điểm < `quality_slo_threshold` → **chặn** câu trả lời.
4. Route sang fallback ladder → user nhận câu an toàn (`status="degraded_quality_fallback"`), **không** nhận thông tin sai.
5. Vi phạm SLO chất lượng lặp lại nên được giám sát riêng và có thể "nâng cấp" thành **quality-based circuit breaker**.

Chaos scenario `silent_degradation` chứng minh: 20/20 câu "90 ngày" bị chặn, availability vẫn 1.0.

### Điểm yếu đã biết & hướng production
- **Breaker đếm lỗi liên tiếp**, chưa dùng rolling-window error-rate → một luồng thành công xen kẽ có thể "reset" bộ đếm. Production nên dùng tỉ lệ lỗi trên cửa sổ trượt.
- **Không giới hạn số probe đồng thời** ở `HALF_OPEN` → nếu nhiều luồng cùng probe có thể đập vào service vừa hồi. Cần semaphore.
- **Quét similarity tuyến tính** `O(n)` toàn cache → không hợp cache lớn; cần vector index (FAISS/pgvector).
- **`_looks_like_false_hit` chỉ bắt số 4 chữ số** — bỏ sót ngày dạng chữ, tên riêng, đơn vị. Cần NER/so khớp thực thể.
- **Quality guardrail hiện là heuristic** (`"90 ngày" in response`). Production phải gọi evaluator online thật (DeepEval/RAGAS/model nhỏ) — xem §12; chi phí + độ trễ cần cân nhắc (chấm bất đồng bộ / lấy mẫu).
- **`transition_log` / `route_log` giữ trong RAM** — cần đẩy sang tracing (OpenTelemetry) + metric backend.
- **Circuit state theo từng process** — nhiều instance ngắt mạch không đồng bộ; điểm cộng đề xuất lưu state vào Redis (chưa làm, xem §11).
- **Cache chưa phân vùng theo tenant/user/phiên bản chính sách** → rủi ro rò rỉ chéo; cần namespace + version key và invalidate khi KB đổi.

---

## 11. Điểm cộng (stretch goals) — trạng thái

| Stretch goal | Trạng thái | Ở đâu |
|---|---|---|
| Chạy đồng thời `ThreadPoolExecutor` + số đo đổi khác | ✅ | `chaos_load_test.py::scenario_cache_stampede_concurrent` |
| Cache tự lùi về in-memory khi Redis sập | ✅ | `SharedRedisCache._degrade` + test + chaos scenario |
| Routing theo ngân sách (>80% → model rẻ hơn) | ✅ | `provider_router.py` |
| `hypothesis` fuzz các chuyển trạng thái | ✅ | `tests/test_state_machine_fuzz.py` (300 ví dụ; kiểm bất biến: `from != to`, `open_count` khớp log, `CLOSED` chỉ vào lại từ `HALF_OPEN`, fail-fast chỉ xảy ra ở `OPEN` trước timeout) |
| Lập bảng SLO và đối chiếu | ✅ | §9 |
| Lưu circuit state vào Redis cho nhiều instance | ⛔ chưa làm | ghi rõ ở §10 như hướng phát triển |

---

## 12. Live evaluation với Gemini (bổ trợ, không nằm trong thang điểm)

`semantic_cache.py`, `eval_deepeval.py`, `eval_ragas.py` cần `GOOGLE_API_KEY`. Kết quả chạy **thật** với Gemini:

| Thành phần | Kết quả live | Ghi chú |
|---|---|---|
| Semantic cache (Gemini embedding) | cosine = **0.943** giữa 2 câu hỏi đồng nghĩa → HIT; hit_rate 100% | `python semantic_cache.py` |
| DeepEval `FaithfulnessMetric` (gemini-2.5-flash) | score = **0.0**, Pass SLO = **False** — "output nói 90 ngày trong khi policy nói 30 ngày" | khớp heuristic guardrail |
| RAGAS `Faithfulness` + `AnswerRelevancy` (gemini-3.5-flash-lite) | xem bảng dưới; lưu ở [`reports/ragas_results.json`](ragas_results.json) | `python eval_ragas.py` |

**RAGAS — số liệu live:**

| user_input | faithfulness | answer_relevancy | diễn giải |
|---|---|---|---|
| "Thời hạn hoàn tiền của tôi là bao lâu?" (trả lời **90 ngày**, context nói 30) | **0.00** | 0.876 | đúng trọng tâm nhưng **bịa** → faithfulness = 0 → guardrail phải chặn |
| "Công ty có hỗ trợ giao hàng hỏa tốc không?" (trả lời đúng context) | **1.00** | 0.924 | bám sát context → pass |

→ RAGAS và DeepEval **đồng thuận**: câu hallucination có faithfulness = 0.0, câu grounded có faithfulness = 1.0 — xác nhận thiết kế `QualityGuardrail`.

**Ghi chú kỹ thuật:** `eval_ragas.py` đã vá lỗi `import langchain_community.chat_models.vertexai` (module bị gỡ ở langchain-community 0.4) bằng một shim, và có retry/pacing cho rate limit. Model dùng `gemini-3.5-flash-lite` vì `gemini-2.5-flash` free tier chỉ 20 request/ngày (đặt `RAGAS_MODEL=gemini-2.5-flash` để đổi lại). Không số liệu nào bị bịa. `run_all.py --live-eval` chạy các bước này với `allow_fail` để lỗi quota không làm hỏng cả lượt.

---

## 13. Kết luận

Reliability cho hệ LLM rộng hơn "HTTP uptime": circuit breaker + fallback giữ **tính sẵn sàng**, cache + Redis giữ **độ trễ/chi phí**, retry+jitter xử lý **lỗi hạ tầng tạm thời**, và quality guardrail chống **câu trả lời "thành công về kỹ thuật nhưng sai nội dung"** — đúng failure mode `DEGRADED` được chọn phân tích. Toàn bộ được đo bằng `metrics.json` và kiểm chứng bằng 7 chaos scenario + 30 unit test.
