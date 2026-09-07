# WP-00 — Engineering Quality, Coding Standards & Optimization

**Ngày thiết kế:** 2026-09-02  
**Trạng thái:** Approved — duyệt specification/roadmap ngày 2026-09-02; chủ dự án tái xác
nhận sau rollout và audit ngày 2026-09-03  
**Áp dụng cho:** `D:\MVP`  
**Quan hệ:** WP-00 là nền kỹ thuật của MVP-1 và mọi work package sau; WP-00 không phải một MVP tính năng riêng.

## 1. Mục tiêu

WP-00 thiết lập năm nhóm quy tắc xuyên suốt:

1. Project Coding Standards.
2. Automated Quality Gates.
3. Code-Quality Optimization.
4. Performance Optimization.
5. Agent Operating Policy.

WP-00 không viết lại sản phẩm, không thay behavior và không biến nhận xét “có thể chậm” thành optimization task.

## 2. Nguồn sự thật và trạng thái

Mọi tuyên bố kỹ thuật trong tài liệu phải mang một trong ba trạng thái:

- **CURRENT:** đã quan sát được trong repository.
- **PROPOSED:** đã chọn trong thiết kế nhưng chưa triển khai.
- **DEFERRED:** chủ động chưa làm cho đến khi đạt điều kiện kích hoạt.

### CURRENT

- Production container hiện dùng CPython 3.11.
- Local virtual environment quan sát được dùng CPython 3.14.6.
- Dải hỗ trợ là Python 3.11 trở lên; Python 3.11 là minimum compatibility, không phải phiên bản bị khóa.
- Backend dùng FastAPI, Pydantic, PostgreSQL, pgvector, Redis, asyncpg và httpx.
- Test hiện có: pytest và một Node CommonJS contract script.
- Frontend là HTML/CSS/JavaScript thuần, classic scripts, không có TypeScript hoặc frontend framework.
- Có hai `pyrightconfig.json` chỉ cấu hình import path; chưa có Pyright CLI/quality gate.
- Root `requirements-dev.txt` pin Ruff 0.16.5; root `pyproject.toml` là nguồn cấu hình Ruff duy nhất với target `py311`, line length 100 và candidate lint rules đã audit.
- Ruff stage 2 ban đầu là report-only: audit ngày 2026-09-03 ghi nhận 103 lint findings
  và 27/29 file Python cần format; stage này không auto-fix hoặc format source.
- Ruff stage 3 dùng `tools/ruff_gate.py` với inventory 31 file; baseline ban đầu có 103
  diagnostic và hiện rỗng sau Stage 4.
- Stage 4 đã cleanup toàn bộ phạm vi Ruff hiện tại: 0 lint diagnostic và 31/31 file pass
  Ruff formatter check.
- Stage 5 đã được chủ dự án duyệt ngày 2026-09-03; gate hiện blocking Ruff lint và format
  trên toàn bộ target, không chỉ file mới.
- SQL schema và query nằm trong `postgres_client.py`; không có migration framework.
- Có ba Compose file chưa thống nhất.
- Git hệ thống dùng `core.autocrlf=true`; root `.gitattributes` ghi đè trong repository bằng
  `text=auto eol=lf`, và root `.editorconfig` yêu cầu UTF-8, LF, newline cuối file.
- Khi policy line-ending được thêm, 52/54 tracked file đã LF; 2 worktree file CRLF hiện hữu
  được giữ nguyên vì change này không chạy renormalization.
- Trước lần tích hợp tài liệu WP-00, repository chưa có `AGENTS.md` hoặc thư mục engineering docs. Bản tích hợp hiện tại bổ sung hai artifact tài liệu này nhưng chưa kích hoạt CI, pre-commit, benchmark framework hoặc coverage tooling.
- Working tree tại ngày audit có nhiều thay đổi chưa commit thuộc quyền sở hữu của người dùng.

### PROPOSED

- Các quy tắc trong root `AGENTS.md` trở thành governance bắt buộc sau khi WP-00 được chủ dự án duyệt.
- Các policy trong `docs/engineering/code-quality.md` và `docs/engineering/performance.md` trở thành chuẩn chi tiết sau khi WP-00 được chủ dự án duyệt.
- Gate mới sau WP-00 bắt đầu với new/changed code; riêng Ruff đã đạt repository-wide
  enforcement tại Stage 5 sau khi debt được xử lý có chủ ý.

### DEFERRED

- Sentence Transformers: không tồn tại và không thuộc WP-00.
- ESLint/Prettier: chờ chủ dự án chọn package manager và duyệt dependency.
- Type-checker CLI: ưu tiên tiếp tục với Pyright nhưng chờ duyệt dependency và scope.
- Coverage threshold: chờ có coverage tool và baseline.
- Pre-commit: chờ local quality commands ổn định.
- CI: chờ local gates ổn định và chủ dự án duyệt GitHub Actions.
- Migration framework: tách thành quyết định kiến trúc khi có schema-changing package.
- Performance budgets: chờ workload và baseline thực tế.

## 3. Quan hệ giữa WP-00 và MVP-1

MVP-1 định nghĩa hệ thống làm gì; WP-00 định nghĩa cách thay đổi hệ thống an toàn.

Thứ tự đọc bắt buộc là: `ai_engine_long_form_story.md` trước, WP-00 sau, rồi mới đến spec của work package đang thực hiện. WP-00 đứng trước các package trong quality-gate order nhưng không đứng trước phần giới thiệu sản phẩm trong reading order.

| MVP-1 capability | WP-00 guardrail |
|---|---|
| Planner/Analyzer/Memory | Type hints, tests, stable boundaries |
| Redis worker | Async, timeout, cancellation, bounded concurrency |
| PostgreSQL/pgvector | Parameterized SQL, bounded reads, query evidence |
| Multi-provider LLM | Per-attempt latency/token/fallback evidence |
| Chapter generation | Correctness và story-quality guardrails |
| Refactor orchestrator | Characterization tests, small change groups |

WP-00 không thay thế Planner, Retriever, Writer, Analyzer, Memory Manager, API, queue hoặc persistence.

## 4. Coding-standard contract

Chi tiết nằm tại [`../engineering/code-quality.md`](../engineering/code-quality.md). Các core rule bắt buộc:

- Python production code hỗ trợ CPython 3.11 trở lên; không dùng cú pháp/API làm mất minimum compatibility 3.11 cho đến khi có quyết định nâng minimum version.
- Không wildcard import, bare `except`, hidden exception swallowing hoặc blocking I/O trong event loop.
- Public API/service/repository/business boundaries có type hints.
- Không thêm `Any` chỉ để im lặng type checking.
- Không dùng `print()` hoặc `console.log()` cho production diagnostics.
- Không log secret, credential, prompt, manuscript hoặc story state đầy đủ.
- SQL nhận input phải parameterized.
- Không giữ database connection/transaction trong lúc gọi LLM dài.
- JavaScript giữ classic-script architecture trong WP-00; không tự chuyển ESM/TypeScript/framework.
- Style-only change không đổi behavior hoặc public contract.
- Không dùng giới hạn số dòng cứng; tách module theo responsibility và khả năng kiểm thử.

## 5. Quality-gate contract

### Existing untouched code

Không sửa chỉ để thỏa rule mới. Warning được ghi debt có nguồn và phạm vi.

### Changed legacy code

Vùng thực sự bị work package thay đổi phải format/lint theo gate đã kích hoạt và không tạo warning mới. “Changed” được tính từ baseline do chủ dự án xác nhận, không tính toàn bộ dirty worktree tồn tại trước WP-00.

### New code

Phải tuân thủ toàn bộ gate đã kích hoạt và có test phù hợp.

### Gate rollout

1. Audit và documentation.
2. Python tool configuration.
3. New/changed-code enforcement.
4. Package-by-package cleanup.
5. Repository-wide enforcement chỉ khi debt đã được xử lý có chủ ý.
6. Performance budgets sau baseline.

Mỗi stage cần entry condition, command, exit condition và rollback. Stage sau không tự động được duyệt.

### Stage 2 record — Python tool configuration

- **Entry:** chủ dự án duyệt root `requirements-dev.txt` và Ruff ngày 2026-09-03.
- **Commands:** `python -m pip install -r requirements-dev.txt`, `python -m ruff check AI_engine/app AI_engine/tests API/main.py --statistics --no-cache`, `python -m ruff format --check AI_engine/app AI_engine/tests API/main.py --no-cache`.
- **Exit:** Ruff 0.16.5 cài được; cấu hình target `py311` đọc được; candidate rules đã audit; legacy findings được giữ report-only.
- **Rollback:** xóa riêng `requirements-dev.txt` và `pyproject.toml`, rồi uninstall Ruff khỏi virtualenv; không cần rollback source vì stage này không sửa hoặc format source.
- **Next gate at stage completion:** stage 3 được chủ dự án duyệt riêng và ghi nhận ngay bên dưới.

### Stage 3 record — New/changed-code enforcement

- **Entry:** chủ dự án xác nhận ngày 2026-09-03 rằng toàn bộ dirty Python WIP hiện tại là legacy baseline.
- **Command:** `python tools/ruff_gate.py`.
- **Exit:** gate pass tại baseline 31 file/103 diagnostic; mutation probe `tools/_ruff_gate_probe.py:F401` bị chặn với exit 1; probe được xóa sau kiểm chứng.
- **Behavior:** diagnostic count theo `file + rule` không được tăng; file Python mới phải lint sạch và pass formatter check.
- **Known limit:** thay một lỗi bằng lỗi khác cùng rule trong cùng file có thể giữ nguyên count; changed-line formatter vẫn cần review thủ công cho đến package cleanup.
- **Rollback:** xóa riêng `tools/ruff_gate.py`, `tools/test_ruff_gate.py`, `tools/ruff-baseline.json` và trả lint/format về report-only; không sửa source legacy.
- **Next gate at stage completion:** stage 4 được duyệt riêng cho `AI_engine/app/workers` và ghi nhận ngay bên dưới.

### Stage 4 record — Package cleanup

#### Package 1: `AI_engine/app/workers`

- **Entry:** chủ dự án duyệt package ngày 2026-09-03; pre-check có 1 `I001` trong `generation_worker.py`.
- **Change:** sắp xếp import và chạy Ruff formatter trên đúng một file; không đổi API hoặc behavior.
- **Exit:** package lint/format sạch; baseline key `generation_worker.py:I001` được gỡ, current debt giảm từ 103 xuống 102.
- **Rollback:** revert riêng diff của `generation_worker.py` và khôi phục đúng baseline key `AI_engine/app/workers/generation_worker.py:I001: 1`.
- **Next package:** chủ dự án yêu cầu tiếp tục ngày 2026-09-03; chọn các module gốc
  trong `AI_engine/app` vì cùng nhỏ nhất với `API` nhưng không đụng API wrapper contract.

#### Package 2: các module gốc trong `AI_engine/app`

- **Entry:** chủ dự án yêu cầu tiếp tục rollout ngày 2026-09-03; pre-check có 2 `I001`,
  mỗi lỗi trong `config.py` và `main.py`.
- **Change:** sắp xếp import và chạy Ruff formatter trên đúng hai file; không đổi API,
  schema hoặc behavior.
- **Exit:** package lint/format sạch; hai baseline key `config.py:I001` và `main.py:I001`
  được gỡ, current debt giảm từ 102 xuống 100.
- **Rollback:** revert riêng thay đổi format/import của `config.py`, `main.py` và khôi phục
  hai baseline key tương ứng.
- **Next package:** `API/main.py` còn 2 diagnostic (`E402`, `I001`); review xác nhận
  `E402` là thứ tự bắt buộc vì wrapper phải bootstrap `sys.path` trước khi import app.

#### Package 3: `API/main.py`

- **Entry:** tiếp tục Stage 4 ngày 2026-09-03; pre-check có `I001` và `E402`.
- **Change:** sắp xếp import, chạy Ruff formatter và thêm suppression `E402` đúng một
  dòng với lý do bootstrap `sys.path`; không đổi API hoặc behavior.
- **Exit:** file lint/format sạch; hai baseline key `API/main.py:I001` và
  `API/main.py:E402` được gỡ, current debt giảm từ 100 xuống 98.
- **Rollback:** revert riêng thay đổi format/import/suppression của `API/main.py` và
  khôi phục hai baseline key tương ứng.
- **Next package:** chọn theo số diagnostic còn lại và rủi ro thay đổi; không tự mở rộng
  cleanup sang package mới trong cùng change group.

#### Stage 4 completion: five-set cleanup

Chủ dự án duyệt phương án cleanup theo domain/rủi ro ngày 2026-09-03. Mỗi set được chạy
targeted Ruff, baseline gate và backend tests trước khi chuyển tiếp.

| Set | Phạm vi | Diagnostic đã gỡ | Baseline sau set |
|---|---|---:|---:|
| 1 | `application/dto/story_dtos.py` | 35 | 63 |
| 2 | API v1, pipeline và application | 16 | 47 |
| 3 | LLM gateway và providers | 13 | 34 |
| 4 | PostgreSQL, Redis và vector store | 14 | 20 |
| 5 | `tests/test_main.py` | 20 | 0 |

- **Manual review:** `E402` trong production router được giải quyết bằng cách chuyển import
  vào import block; các late import cần thiết trong test dùng line-level suppression có lý
  do. `B023`, nested context manager và mock `timeout` được xử lý trong đúng phạm vi rule.
- **Residual format:** `domain/exceptions/story_exceptions.py` không có lint diagnostic nhưng
  còn một format delta; file này được format riêng để toàn bộ 31 file cùng sạch.
- **Exit:** full Ruff lint pass; full Ruff formatter check pass; baseline diagnostic rỗng;
  backend `50 passed` và frontend story contract pass. Còn một warning Starlette/httpx đã
  biết; không thêm dependency trong Stage 4.
- **Rollback:** rollback theo từng set bằng chính diff của set và khôi phục các baseline key
  tương ứng; không dùng reset hoặc ghi đè dirty WIP của chủ dự án.
- **Next stage:** chủ dự án duyệt Stage 5 sau khi được giải thích phạm vi và tác động.

### Stage 5 record — Repository-wide local enforcement

- **Entry:** Stage 4 kết thúc với 0 lint diagnostic và 31/31 file pass formatter; chủ dự án
  yêu cầu tiếp tục ngày 2026-09-03.
- **Behavior:** `tools/ruff_gate.py` luôn chạy `ruff format --check` trên toàn bộ target đã
  cấu hình. Một file hiện hữu bị lệch format làm gate fail, kể cả khi không có file mới.
- **TDD evidence:** test `test_main_fails_when_existing_target_needs_formatting` ban đầu
  fail với `AssertionError: 0 != 1`, sau thay đổi pass; toàn bộ 3 gate unit tests pass.
  Probe tạm `_ruff_format_probe.py` bị gate chặn với exit 1 và được xóa sau kiểm chứng.
- **Scope:** giữ nguyên lint baseline schema, target list và dependency; không thêm CI,
  pre-commit, package manager hoặc formatter khác.
- **Rollback:** trả formatter invocation về chỉ chạy trên file mới; giữ nguyên Stage 4
  source cleanup và lint baseline rỗng.

### Line-ending policy record

- **Entry:** chủ dự án duyệt phương án dùng cả `.editorconfig` và `.gitattributes` sau khi
  review tác động của `core.autocrlf=true`.
- **Change:** `.editorconfig` đặt UTF-8, LF và newline cuối file; `.gitattributes` đặt
  `* text=auto eol=lf` để Git dùng LF cho text nhưng vẫn tự nhận diện binary.
- **Boundary:** không đổi Git config toàn máy, không chạy `git add --renormalize .` và không
  rewrite dirty WIP.
- **Evidence:** `git check-attr` trả `text: auto`, `eol: lf`; 52 tracked file giữ LF và 2
  worktree file CRLF hiện hữu chưa bị đổi. Filtered/raw hash của PNG giống nhau, xác nhận
  `text=auto` không biến đổi binary trong probe.
- **Rollback:** xóa riêng hai file policy; không cần rollback nội dung source vì không có
  renormalization trong change này.

### WP-00 ownership manifest

- **Governance và tooling scope:** `.editorconfig`, `.gitattributes`, `AGENTS.md`,
  `docs/engineering/code-quality.md`, `docs/engineering/performance.md`, tài liệu WP-00 này,
  `pyproject.toml`, `requirements-dev.txt`, `tools/ruff_gate.py`,
  `tools/test_ruff_gate.py` và `tools/ruff-baseline.json`.
- **Mechanical cleanup scope:** inventory 31 file trong `tools/ruff-baseline.json` là nguồn
  danh sách duy nhất. WP-00 chỉ nhận ownership cho import ordering, Ruff formatting,
  lint fix/suppression đã ghi tại Stage 4 và thay đổi gate tại Stage 5.
- **User-owned WIP:** mọi thay đổi logic nghiệp vụ hoặc nội dung có trước WP-00, kể cả khi
  nằm cùng file với mechanical cleanup, vẫn thuộc chủ dự án. Manifest này không tái phân
  loại, stage, commit, reset hoặc cho phép ghi đè các thay đổi đó.
- **Integration status:** chủ dự án tái xác nhận phê duyệt WP-00 ngày 2026-09-03 sau khi
  review audit và ownership manifest. Toàn bộ governance/tooling scope phía trên hiện chưa
  được Git track; repository không có staged change hoặc commit do agent tạo.

## 6. Refactor và optimization contract

- Characterization test phải pass trước refactor có rủi ro.
- Refactor, formatting, behavior change, dependency upgrade và performance optimization được tách thành change group/commit riêng khi diff đáng kể.
- Chỉ tối ưu sau khi có scenario, workload, metric, baseline, bottleneck và hypothesis.
- So sánh trước/sau trên cùng môi trường hoặc nêu rõ sai khác.
- Improvement nằm trong measurement noise không được giữ chỉ vì “có vẻ nhanh hơn”.
- Optimization không được làm giảm continuity, fact retention hoặc retrieval relevance ngoài ngưỡng được chủ dự án duyệt.
- Live-provider benchmark cần model, call limit, token budget, cost limit và stop condition được duyệt.

Chi tiết nằm tại [`../engineering/performance.md`](../engineering/performance.md).

## 7. Data và database safety

- Benchmark mặc định dùng synthetic/anonymized data.
- Không commit prompt, prose, manuscript, production dump, API key, cookie, authorization header hoặc connection string.
- Mặc định chỉ lưu metadata đã sanitize: length, hash, latency, token và status.
- `EXPLAIN ANALYZE` thực thi query; write query chỉ được chạy trên database benchmark cô lập hoặc transaction đã đánh giá đầy đủ side effect.
- WP-00 không thay đổi schema và không tự cài migration framework.

## 8. Baseline ngày 2026-09-02 và trạng thái hiện tại

| Check | Result | Limitation |
|---|---|---|
| Backend pytest | 50 passed | 1 Starlette/httpx deprecation warning |
| Frontend contract | Passed | Một Node script, không phải test runner/package |
| Python AST parse | 29 files passed | Không thay thế type checking |
| Coverage | Not measured | `pytest-cov` không tồn tại |
| Ruff lint | 0 current findings | Initial audit 103; Stage 4 đã cleanup toàn bộ phạm vi hiện tại |
| Ruff format | 31/31 files pass | Full check đã chạy; blocking toàn phạm vi từ Stage 5 |
| Pyright | Not measured | Config path có, CLI không có |
| Performance | Not measured | Chưa có workload/cost approval |

Baseline này là evidence của audit, không phải quality threshold vĩnh viễn.

## 9. Stop conditions

Agent phải dừng trước khi:

- thêm dependency/tool hoặc package manager chưa được duyệt;
- đổi architecture, public API, schema, migration history hoặc error contract;
- format/refactor ngoài phạm vi;
- dùng user/production data cho benchmark;
- gọi provider thật khi thiếu cost limit;
- thêm cache khi thiếu key/invalidation/lifetime/ownership;
- thêm concurrency khi thiếu bound/timeout/cancellation;
- ghi đè dirty change chưa rõ ownership;
- tuyên bố pass/improvement khi verification không chạy được.

Không hỏi lại quyết định đã có bằng chứng và đã được chủ dự án ghi nhận.

## 10. Traceability

| Rule | Source/config | Local command | CI | Status |
|---|---|---|---|---|
| Python syntax/tests | pytest + source | `python -m pytest` | Không có | CURRENT |
| Frontend contract | Node script | `node tests/story_contract.test.js` từ `API` | Không có | CURRENT |
| Python format | root `pyproject.toml` + Ruff targets | `python tools/ruff_gate.py` | Không có | CURRENT — blocking toàn phạm vi từ Stage 5 |
| Python lint | root `pyproject.toml` + baseline rỗng | `python tools/ruff_gate.py` | Không có | CURRENT — mọi lint diagnostic mới làm gate fail |
| Type checking | existing Pyright config | Chờ CLI approval | Chờ local gate | DEFERRED |
| JS format/lint | Chờ package manager | Chờ dependency approval | Chờ local gate | DEFERRED |
| Coverage | Chờ coverage tool | Chờ dependency approval | Chờ baseline | DEFERRED |
| Performance | performance policy | Command theo experiment đã duyệt | Không chạy trong main CI mặc định | DEFERRED |

## 11. Definition of Done của WP-00

WP-00 chỉ có thể được đề xuất chuyển sang `Approved` khi:

- CURRENT/PROPOSED/DEFERRED phản ánh đúng repository.
- Core rules và engineering docs được chủ dự án duyệt.
- Mọi dependency/tool có quyết định explicit hoặc trạng thái DEFERRED có điều kiện kích hoạt.
- Local command được kiểm chứng cho gate đã kích hoạt.
- Baseline/coverage/performance không chứa số tự đặt.
- Không format toàn repository và không đổi behavior ngoài chủ ý.
- Git diff được review với ownership rõ.
- Chủ dự án tự xác nhận trạng thái `Approved`; agent không tự chuyển trạng thái.

## 12. Quyết định còn mở

Các quyết định này không chặn việc duyệt specification, nhưng chặn stage tooling tương ứng:

1. **Resolved 2026-09-03:** dev dependencies dùng root `requirements-dev.txt`; Ruff pin 0.16.5.
2. JavaScript dùng npm, pnpm, Yarn hay tiếp tục deferred enforcement?
3. Pyright CLI được thêm hay chỉ giữ editor import-path config?
4. Có thêm `pytest-cov` để đo baseline không?
5. Có dùng pre-commit sau khi local gate ổn định không?
6. Root Compose có được xác nhận là deployment definition canonical không?
7. Có triển khai GitHub Actions sau local rollout không?

## 13. Rollback

- Documentation có thể revert độc lập với tooling.
- Tool configuration phải được thêm thành change group riêng.
- Enforcement có thể chuyển từ blocking về report-only mà không xóa rule hoặc baseline.
- Không rollback bằng cách xóa hoặc ghi đè thay đổi chưa commit của người dùng.
