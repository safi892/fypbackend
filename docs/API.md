# API Reference

## Health

`GET /health`

Response:

```json
{ "status": "ok" }
```

## Analyze

`POST /analyze`

Request:

```json
{
  "code": "int add(int a, int b) { return a + b; }"
}
```

Response:

```json
{
  "input_code": "...",
  "commented_code": "...",
  "explanation": "..."
}
```

## Auth

`POST /auth/register`

Request:

```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "password": "secret123",
  "confirmPassword": "secret123"
}
```

`POST /auth/login`

Request:

```json
{
  "email": "john@example.com",
  "password": "secret123"
}
```

`GET /auth/me`

Headers:

```text
Authorization: Bearer your-session-token
```

`POST /auth/logout`

Headers:

```text
Authorization: Bearer your-session-token
```

## POST /optimize

Return a faster version of the submitted code, when one can be proven correct.

Commenting and explaining describe code; this changes it, which is a different
promise. The proposal is compiled next to the original, both are run on the
same inputs, and it is only returned when the outputs agree — so a rewrite that
computes something else never reaches the client.

**Request**

```json
{ "code": "int fib(int n) { ... }", "source": "mobile", "language": "cpp" }
```

**Response**

```json
{
  "input_code": "int fib(int n) { ... }",
  "code": "int fib(int n) { ... dp table ... }",
  "changed": true,
  "verified": true,
  "speedup": 2.58,
  "note": "equivalent on 8 inputs, 2.6x faster"
}
```

| field | meaning |
| --- | --- |
| `code` | the rewrite, or **the original unchanged** when none was accepted |
| `changed` | whether `code` differs from `input_code` |
| `verified` | compiled, executed and matched the original |
| `speedup` | measured ratio; `0` when the work was too small to time |
| `note` | what was checked, in words |

Show `verified` rather than implying every rewrite was proven: some function
shapes cannot be driven automatically, and those return `changed: true` with
`verified: false`.

Requires `Authorization: Bearer <token>`. Empty `code` gives 422.

## GET /ready

Whether this machine can actually answer requests: the model file, the
inference server, and the C++ compiler used to verify optimisations. Always
returns 200 — read `ready`, and `next_step` when it is false.

`/health` remains the cheap liveness probe and does not touch the model.

## New fields on POST /analyze

All optional and additive; an existing client is unaffected.

| field | meaning |
| --- | --- |
| `line_comments` | `{line, code, comment}` records, each checked against the submission |
| `anchor_stats` | how many comments were proposed, kept, relocated, dropped |
| `verified_comments` | `commented_code` is the caller's own source with comments attached |

When `verified_comments` is true, `commented_code` contains the submitted source
verbatim — comments are appended, never a model's rewrite of the code. Comments
referring to lines that are not in the submission are dropped, and `anchor_stats.dropped`
counts them.
