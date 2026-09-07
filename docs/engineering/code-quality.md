# AI Story Platform — Code Quality Standard

**Authority:** WP-00  
**Status:** Approved — chủ dự án duyệt 2026-09-02

## 1. Compatibility và source boundaries

- Dải hỗ trợ là CPython 3.11 trở lên. Python 3.11 là minimum compatibility, không phải version pin; development và deployment được phép dùng runtime mới hơn.
- Python app nằm trong `AI_engine/app`; Python wrapper nằm trong `API/main.py`.
- Frontend hiện là `API/static/*.js`, `index.html` và `style.css`.
- Không tự chuyển classic scripts sang ESM, JavaScript sang TypeScript hoặc static frontend sang framework.
- SQL hiện nằm trong Python repository/database module; WP-00 không di chuyển SQL chỉ để đạt style.

## 2. Python

- PEP 8 với line length 100.
- Ruff formatter quyết định quote/wrapping khi gate được kích hoạt.
- Ruff linter chịu trách nhiệm import sorting; candidate rules ban đầu: `E4`, `E7`, `E9`, `F`, `I`, `UP`, `B`, `SIM`, `ASYNC`.
- Candidate rules phải được audit tác động trước khi chốt; không bật hàng loạt bằng auto-fix trên legacy code.
- Indentation 4 spaces; UTF-8; LF; newline cuối file.
- Root `.editorconfig` hướng dẫn editor và `.gitattributes` là nguồn quyết định line ending
  của Git; không renormalize hàng loạt trong cùng change với việc thêm policy.
- Dùng `list[str]`, `dict[str, Any]`, `X | None`; không dùng cú pháp hoặc API chỉ có từ Python 3.12+ nếu chưa nâng minimum compatibility bằng quyết định riêng.
- Public API, service, repository và business boundary có argument/return type hints.
- Không wildcard import, unused import/variable, bare `except`, swallowed exception hoặc mutable function default.
- Với Pydantic collection defaults, ưu tiên `Field(default_factory=...)` để ý định rõ và tool-friendly.
- Không dùng `Any` chỉ để né type checker.
- Không dùng `print()` trong application code.
- Logging ưu tiên lazy interpolation: `logger.info("job=%s", job_id)`.
- Không gọi blocking I/O trực tiếp trong event loop.
- Chỉ dùng async khi có asynchronous I/O hoặc concurrency hợp lý.

## 3. JavaScript

Style hiện hữu cần bảo toàn cho đến khi formatter được duyệt:

- 4-space indentation.
- Single quote cho string thông thường.
- Semicolon.
- `camelCase` cho variable/function, `PascalCase` cho class, `UPPER_SNAKE_CASE` cho global constant bất biến.
- Ưu tiên `const`; dùng `let` khi gán lại; không dùng `var`.
- Dùng `===` và `!==`.
- Không floating promise, empty catch hoặc production `console.log`.
- Không trộn promise chaining và `async/await` trong cùng flow khi không có lý do.
- Giữ load order của classic scripts và global class contract cho đến khi có package riêng thay đổi module system.

ESLint/Prettier là DEFERRED, không được tự tạo `package.json` hoặc chọn npm/pnpm/Yarn.

## 4. HTML/CSS

- Semantic HTML và keyboard accessibility là yêu cầu correctness.
- Mỗi page có heading hierarchy hợp lệ.
- Control tương tác có accessible name và visible focus.
- Tôn trọng `prefers-reduced-motion` khi animation không thiết yếu.
- Không áp BEM, CSS Modules, utility framework hoặc Stylelint nếu chưa có proposal riêng.
- Không đổi visual identity trong style-only package.
- Formatter HTML/CSS chỉ được bật cùng frontend tooling đã duyệt.

## 5. SQL

- Input phải parameterized; không nối user input vào SQL.
- Không đổi schema naming hoặc startup migration behavior trong WP-00.
- Tránh `SELECT *` khi production flow chỉ cần một subset rõ ràng.
- Query có khả năng trả nhiều row phải bounded/paginated hoặc ghi rationale.
- Không thêm index nếu chưa có query evidence và read/write/storage trade-off.
- Không giữ connection/transaction trong external LLM call.

## 6. Logging, errors và secrets

- Log có component/operation/job/request context khi phù hợp.
- Không log API key, cookie, auth header, connection string, prompt, full prose/manuscript hoặc story state mặc định.
- Exception được xử lý tại layer có đủ context; tránh log rồi rethrow lặp ở nhiều layer.
- Không trả stack trace hoặc provider payload thô cho client.
- Error contract hiện tại chưa thống nhất; WP-00 ghi debt nhưng không đổi public response.

## 7. Module/class/function

- Không dùng line-count threshold máy móc.
- Một module có một mục đích kết dính; class có một trách nhiệm chính; function làm một công việc mô tả được.
- Tách khi có nhiều abstraction level, nesting khó hiểu, side effect ẩn hoặc khó test.
- Không tạo `utils.py`/`helpers.py` làm nơi gom logic không liên quan.
- Không tạo interface/design pattern cho implementation giả định trong tương lai.
- DRY chỉ áp dụng khi duplication có cùng nghĩa nghiệp vụ và đã đủ ổn định.

## 8. Tests và documentation

- Test name mô tả behavior; Arrange–Act–Assert hoặc cấu trúc tương đương.
- Test không phụ thuộc thứ tự và unit test không gọi network/provider thật.
- Bug fix có regression test khi có thể tái hiện.
- Behavior change có test chứng minh behavior mới.
- Không xóa/làm yếu test để gate pass.
- Comment giải thích “vì sao”; public contract và architecture decision quan trọng phải được document.
- Behavior/interface đổi thì documentation đổi trong cùng work package.

## 9. Enforcement scope

- Untouched legacy code: report-only.
- Changed legacy code: gate vùng thay đổi, không tạo warning mới.
- New code: pass toàn bộ gate đã kích hoạt.
- Không chạy repository-wide auto-fix trong WP-00.
- Dirty files tồn tại trước baseline không tự động thuộc phạm vi WP-00.

Local Python gate từ 2026-09-03 là `python tools/ruff_gate.py`:

- Baseline ban đầu gồm 31 file Python và 103 diagnostic legacy; sau Stage 4 cleanup
  ngày 2026-09-03 còn 0 diagnostic và toàn bộ 31 file trong phạm vi gate pass Ruff
  formatter check.
- Gate fail khi số diagnostic theo cùng `file + rule` tăng; vì baseline hiện rỗng,
  mọi Ruff lint diagnostic mới đều làm gate fail.
- Mọi file Python trong target hiện tại phải không tạo lint diagnostic và phải pass Ruff
  formatter check; Stage 5 chạy formatter check trên toàn phạm vi ở mỗi lần chạy gate.
- Giới hạn same-rule replacement của count baseline không còn áp dụng khi baseline rỗng.

## 10. Suppression

- Scope nhỏ nhất, lý do cụ thể, ưu tiên line-level.
- Suppression tạm thời có issue/debt reference.
- Không global-ignore warning mới hoặc dùng suppression để che bug.
