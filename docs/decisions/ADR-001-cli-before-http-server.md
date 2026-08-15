# ADR-001: Keep the CLI until an HTTP boundary is required

- Status: accepted
- Date: 2026-08-15
- Related story: [US-001](../user-stories/completed/US-001-agentic-repository-bootstrap.md)

## Context

The bootstrap request considered Uvicorn, but the implemented behavior is local foreground Win32
input. No remote consumer, browser UI, HTTP API, or concurrent request model is currently defined.

## Decision

Keep the application as an installable CLI. Do not add FastAPI, Uvicorn, or another server until an
accepted user story defines an HTTP consumer, API contract, lifecycle, and security boundary.

## Alternatives

- Add an ASGI server now: rejected because it creates dependencies and attack surface without a
  current capability.
- Build a Windows desktop UI now: deferred until the intended operator workflow is known.

## Consequences

- Setup and testing stay small and local.
- A later UI story may introduce an application service boundary before adding a transport adapter.
- CLI output remains internationalized and stable enough for manual operation.

## Verification

`pyproject.toml` has no runtime dependencies, and the application is exposed through the
`flyff-bot` console script.

