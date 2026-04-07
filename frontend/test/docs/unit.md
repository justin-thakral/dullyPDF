# Unit Testing Guide (Frontend)

Frontend unit tests live in `frontend/test/unit/` and are implemented as executable
`*.test.ts` / `*.test.tsx` files grouped by area.

## Scope

Frontend unit tests should validate deterministic behavior in isolation:

- utility and parsing logic (`frontend/src/utils/*`)
- API/request adapters and auth state helpers (`frontend/src/services/*`)
- component interaction behavior (forms, toggles, validation, callbacks)
- rendering-state transitions (loading, empty, error, success)

Avoid real network calls and real Firebase/OpenAI calls in unit tests.

## Stack

- `vitest` for runner and assertions
- `@testing-library/react` for component rendering
- `@testing-library/user-event` for interaction flows
- `jsdom` test environment configured in `frontend/vite.config.ts`
- shared setup in `frontend/test/setup.ts`

## Location and Naming

- Tests live under `frontend/test/unit/`
- Use area-based folders (`components/`, `utils/`, `services/`, `api/`, etc.)
- Use `test_<area>.test.ts` / `test_<area>.test.tsx` naming

## Run Unit Tests

From `frontend/`:

```bash
npm run test
```

Run a subset:

```bash
npm run test -- test/unit/utils/test_csv.test.ts
```

From repo root:

```bash
cd frontend && npm run test
```

Hybrid QA uses a lighter split so routine app changes do not always pay for the static-content and legacy suites:

```bash
npm run test:frontend:ci
npm run test:frontend:content
```

`test:frontend:ci` skips the marketing/docs/SEO suites that mostly assert static copy, route metadata, prerendered public-page wiring, and legacy fixtures. Run `test:frontend:content` when you actually changed those content/config surfaces.

## Test Authoring Rules

1. Mock external boundaries (`fetch`, Firebase SDK, PDF.js, browser observers, timers).
2. Keep assertions user-visible and behavior-focused.
3. Prefer targeted assertions over broad snapshots.
4. Keep tests deterministic (mock time, randomness, and async timing where needed).
5. Add both happy-path and edge/error-path coverage.

## Important Frontend Notes

- `main.tsx` performs a best-effort `/api/health` warmup request; mock `fetch` in entrypoint tests.
- Some modules require browser-only APIs (`ResizeObserver`, `IntersectionObserver`, `MutationObserver`, `DOMParser`, `grecaptcha`, `CSS.escape`); use setup mocks or test-local mocks.
- For async UI, prefer user-centric waits/assertions over internal implementation details.

## Failing Tests Policy

Failing tests are acceptable only as short-term debugging signals while fixing behavior.
A failing test is not a done state for merge.

When a test fails:

1. Verify the test setup and assertions first.
2. If the test is wrong, fix the test.
3. If product code is wrong, report failing test ids and expected vs actual behavior.
4. Write a detailed bug report in `test/bugs/` as `YYYY-MM-DD_<area>_<short-slug>.md`.

## Definition of Done

- Covered scenarios for the module are implemented.
- External boundaries are mocked.
- Edge cases are covered (not only happy path).
- Tests pass repeatedly and deterministically.
