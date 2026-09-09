"""Pydantic v2 request/response schemas — the API's shared type contract.

Design decision (not specified in the brief, noted per instructions): rather
than a codegen step, `frontend/src/types/api.ts` is hand-maintained to mirror
these schemas field-for-field, and `docs/API.md` documents the pairing. A
mismatch is caught by the vitest fixtures in Step 7 asserting shape against
the OpenAPI schema FastAPI generates from these classes at `/openapi.json`.
Revisit with real codegen (openapi-typescript) once the surface stabilizes
past Step 6.
"""
