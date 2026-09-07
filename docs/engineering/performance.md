# AI Story Platform — Performance Optimization Standard

**Authority:** WP-00  
**Status:** Approved — chủ dự án duyệt 2026-09-02

## 1. Required evidence

Mỗi optimization phải ghi:

```text
Scenario:
Representative workload:
Metric:
Baseline:
Observed bottleneck:
Hypothesis:
Expected benefit:
Regression risk:
Correctness guardrail:
Story-quality guardrail:
```

Nếu thiếu evidence, ghi hypothesis backlog; không tạo implementation task.

## 2. Workflow

```text
Measure baseline
→ Locate bottleneck
→ Form hypothesis
→ Add benchmark/performance test
→ Implement the smallest useful change
→ Run correctness tests
→ Measure again
→ Compare
→ Record trade-offs
```

Không tuyên bố nhanh/nhẹ/rẻ/tối ưu hơn nếu thiếu số trước và sau.

## 3. Metrics theo layer

- API: p50/p95/p99, error rate, throughput.
- Queue: queue depth, queue waiting time, oldest-job age.
- Worker: processing time, jobs/time unit, retry/recovery count.
- Database: query count/duration, pool wait/saturation, rows read/returned.
- Retrieval: embedding calls, candidate count, top-k, latency, relevance/recall.
- LLM: per-attempt latency, time-to-first-token, token, provider retry/fallback, total cost.
- Chapter: total generation time, revision count, ready/manual-review result.
- Runtime: CPU, memory và event-loop lag khi liên quan.

Chỉ đo metric phục vụ hypothesis hiện tại.

## 4. LLM-specific measurement

- Tách queue wait, internal processing và external-provider latency.
- Ghi mọi provider/model attempt, bao gồm internal Gemini fallback và gateway fallback khi quan sát được.
- Mock benchmark dùng cho reproducible correctness/overhead.
- Live-provider observation chấp nhận variance, cần nhiều sample và cost approval.
- Không coi một LLM-as-judge score là bằng chứng tuyệt đối.
- Reuse/cache output cần story-state version, cache key, invalidation, lifetime và owner.

## 5. Story-quality guardrails

Chọn guardrail liên quan từ:

- mandatory-event retention;
- direct continuity contradictions;
- character/world-rule consistency;
- retrieval relevance/recall;
- fact retention và context truncation;
- repetition;
- analyzer blocking/manual-review rate;
- regeneration/user-edit/user-approval rate.

Threshold chỉ được đặt sau baseline hoặc user approval.

## 6. Database safety

- Dùng `EXPLAIN` trước khi cần execution statistics.
- `EXPLAIN ANALYZE` thực thi query.
- Write/locking/side-effect query chỉ chạy analyze trên isolated synthetic benchmark DB hoặc transaction đã đánh giá rollback limits.
- Rollback không đảo external call, queue message, notification hoặc mọi sequence effect.
- Không chạy production write benchmark nếu thiếu explicit approval.

## 7. Reproducibility

Report ghi ngày giờ, commit SHA, OS/hardware, Python/Node/PostgreSQL version, provider/model, dataset hash, configuration, warm-up, samples, command, units, variance/percentiles, correctness và quality result.

Không so sánh hai environment khác nhau mà không cảnh báo. Microbenchmark không thay end-to-end test; benchmark không thay correctness test.

## 8. Data protection và cost

- Dataset synthetic, anonymized hoặc explicitly approved.
- Không commit raw user story, prompt, production dump, secret hoặc provider payload nhạy cảm.
- Mặc định lưu length/hash/token/latency/status đã sanitize.
- Live provider cần max calls, token budget, cost limit và stop condition.
- Thiếu cost limit thì không chạy live benchmark.

## 9. Performance budget

Trạng thái hiện tại:

```text
Performance budget: pending baseline measurement and product target.
```

Budget chỉ được đề xuất sau khi workload, environment, internal/external latency và product objective được ghi rõ.

## 10. Report format

```text
| Metric | Unit | Environment | Baseline | Candidate | Delta | Samples | Result |

Scenario:
Dataset/version:
Command:
Correctness tests:
Story-quality guardrails:
Cost:
Known limitations:
Decision:
```

Dùng `N/A`, `Not measured` hoặc `Pending approval` kèm lý do; không điền số giả.

