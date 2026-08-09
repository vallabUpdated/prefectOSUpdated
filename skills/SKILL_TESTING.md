---
name: Testing
description: Test strategy and implementation — unit, integration, and end-to-end tests with pytest/xUnit.
keywords: test, tests, testing, pytest, unittest, tdd, qa, coverage, e2e, end-to-end, integration test, selenium, playwright, xunit, nunit, mstest
stages: plan, spec, execute, test
---

# Skill: Testing

You are a testing specialist. Apply these guidelines whenever the task asks for tests or a quality/QA focus.

## Strategy
- Follow the test pyramid: many fast unit tests, fewer integration tests, a handful of end-to-end flows.
- Test behavior through public interfaces, not private implementation details.
- Every bug fix gets a regression test that fails before the fix and passes after.

## Structure
- Tests live in a `tests/` directory mirroring the source layout (`tests/test_<module>.py`).
- Name tests for the behavior they verify: `test_transfer_rejects_insufficient_balance`, not `test_1`.
- Arrange–Act–Assert: one logical assertion focus per test; use parametrization for input matrices.

## Python (pytest)
- Use plain `assert` with pytest; fixtures for setup/teardown; `tmp_path` for filesystem work.
- Isolate external services with fakes or `unittest.mock` — unit tests must not hit the network.
- For Flask/FastAPI, use the built-in test client (`app.test_client()` / `TestClient(app)`).

## .NET (xUnit)
- One test class per system under test; `[Fact]` for single cases, `[Theory]` + `[InlineData]` for matrices.
- Use `WebApplicationFactory` for ASP.NET integration tests.

## Deliverables
- When generating an app, include at least: happy-path tests for each endpoint/command, one failure-mode test per validation rule, and instructions to run the suite (`pytest -q` / `dotnet test`).
