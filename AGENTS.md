# AI Story Platform Engineering Rules

- Treat existing dirty changes as user-owned; never overwrite, reset or reformat them.
- Support CPython 3.11 and newer; do not raise the minimum above 3.11 without explicit approval and corresponding CI evidence.
- Read `ai_engine_long_form_story.md` first to understand the product, architecture and MVP-1.
- Read `docs/engineering/code-quality.md` before changing source.
- Read `docs/engineering/performance.md` before claiming or implementing an optimization.
- Do not add dependencies, package managers, migrations, CI, caches or concurrency without explicit approval.
- Do not change public API/schema/behavior in a style-only change.
- Protect risky refactors with characterization tests.
- Never use live LLM providers or user story data for tests/benchmarks without approved limits.
- Run relevant verification and report actual evidence before claiming completion.

