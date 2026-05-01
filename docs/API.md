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
