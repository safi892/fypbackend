# API Reference & Implementation Guide

This document describes all endpoints provided by the Code Analyzer Backend and demonstrates how developers can integrate, call, and test them.

---

## Interactive Testing Environments

### 1. Browser Playground UI
Open your browser to:
```text
http://localhost:8000/
```
The playground is a zero-build, single-page interface served directly by the backend. It offers:
- Live C++ syntax validation as you type.
- Single unified code card toggleable between **Commented code** (with function-level Javadoc/Doxygen docstrings and inline line comments) and **Optimized code** (recursion-to-loop conversion with comments and verification status).
- Language switcher for English vs. Roman Urdu.
- Preloaded code examples and copy buttons.

### 2. Interactive Swagger / OpenAPI Documentation
Open your browser to:
```text
http://localhost:8000/docs
```
or ReDoc at:
```text
http://localhost:8000/redoc
```
You can test every endpoint directly using the interactive **"Try it out"** button.

---

## Table of Endpoints

| Method | Endpoint | Auth Required | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | No | Serves the browser testing playground |
| `GET` | `/health` | No | Cheap liveness probe |
| `GET` | `/ready` | No | Comprehensive readiness probe (compiler, llama-server, model) |
| `POST` | `/validate-code` | No | Fast C++ syntax validation & quick-fix suggestions |
| `POST` | `/analyze` | Optional | Code commenting, function docstrings & explanation |
| `POST` | `/optimize` | Optional for `web` | Verified optimization & recursion-to-loop conversion |
| `POST` | `/auth/register` | No | Register a new user |
| `POST` | `/auth/login` | No | Login and obtain a session Bearer token |
| `GET` | `/auth/me` | Yes (`Bearer`) | Fetch current authenticated user profile |
| `POST` | `/auth/logout` | Yes (`Bearer`) | Invalidate session token |
| `GET` | `/analyze/history`| Yes (`Bearer`) | Paginated user code analysis history |

---

## 1. System Health & Readiness

### `GET /health`
Confirms the FastAPI server process is running without invoking AI models or database queries.

#### Response (`200 OK`)
```json
{
  "status": "ok"
}
```

#### cURL
```bash
curl -X GET http://localhost:8000/health
```

---

### `GET /ready`
Checks all backend prerequisites:
- Presence of the GGUF model file on disk
- Connectivity to the inference engine (`llama-server`)
- Availability of a local C++ compiler (`g++` / `clang++`) for compile-verification

#### Response (`200 OK`)
```json
{
  "ready": true,
  "model_file": true,
  "llama_server": true,
  "compiler": true,
  "next_step": ""
}
```

#### cURL
```bash
curl -X GET http://localhost:8000/ready
```

---

## 2. Syntax Validation

### `POST /validate-code`
Validates C++ code structure using Tree-Sitter without running AI models or database writes. If a punctuation token (like a missing semicolon or bracket) is detected, it returns an autofix suggestion.

#### Request Body
```json
{
  "code": "int add(int a, int b) { return a + b }"
}
```

#### Response (`200 OK`)
```json
{
  "valid": false,
  "message": "Only C++ source code is supported. Check the syntax near line 1. Finish your statement and check for missing semicolons or brackets.",
  "line": 1,
  "suggested_fix": {
    "code": "int add(int a, int b) { return a + b; }",
    "description": "Add missing ';' before '}'",
    "edits": [
      {
        "line": 1,
        "before": "int add(int a, int b) { return a + b }",
        "after": "int add(int a, int b) { return a + b; }"
      }
    ]
  }
}
```

#### cURL
```bash
curl -s -X POST http://localhost:8000/validate-code \
  -H "Content-Type: application/json" \
  -d '{"code": "int add(int a, int b) { return a + b }"}'
```

---

## 3. Code Analysis & Commenting

### `POST /analyze`
Runs deterministic static analysis, Tree-Sitter parsing, and model inference to produce:
1. **Function-Level Docstrings**: Multi-line Javadoc/Doxygen block comments placed directly above each function:
   - `Function`: Function identifier.
   - `Summary`: Concise description of what the function accomplishes.
   - `Inputs`: Parameters accepted (e.g. `int a[], int n`), or `None (takes no parameters)`.
   - `Process`: How the algorithm executes (e.g., loops, recursion, helper calls, conditional updates).
   - `Returns`: Return type (e.g. `int` or `void (no return value)`).
2. **Inline Comments**: Line-by-line comments verifying operations.
3. **High-Level Explanation**: Prose describing Purpose, Inputs, Outputs, and Algorithm.
4. **Safety & Review Signals**: Flags indicating if comments were dropped or refuted.

#### Request Body
```json
{
  "code": "#include <iostream>\nusing namespace std;\n\nint f(int a[], int n) {\n    int x = a[0];\n    for (int i = 1; i < n; i++)\n        if (a[i] > x)\n            x = a[i];\n    return x;\n}\n\nint g(int a[], int n) {\n    int x = a[0];\n    for (int i = 1; i < n; i++)\n        if (a[i] < x)\n            x = a[i];\n    return x;\n}\n\nint h(int a[], int n) {\n    if (n == 0)\n        return 0;\n    return a[n - 1] + h(a, n - 1);\n}\n\nint k(int a[], int n) {\n    int x = f(a, n);\n    int y = g(a, n);\n    int z = h(a, n);\n    return x - y + z;\n}",
  "output_language": "english",
  "source": "web"
}
```

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `code` | string | Yes | — | C++ source code to analyze (max 100,000 characters). |
| `output_language` | string | No | `"english"` | Language for explanation and comments (`"english"` or `"roman_urdu"`). |
| `old_code` | string | No | `null` | Previous version of code for diff comparison. |
| `source` | string | No | `"web"` | Client platform tag (`"web"` or `"mobile"`). |

#### Response (`200 OK`)
```json
{
  "input_code": "...",
  "commented_code": "#include <iostream>\nusing namespace std;\n\n/**\n * Function: f\n * Summary: Finds the maximum element.\n * Inputs: int a[], int n\n * Process: Iterates through elements in a loop, applying conditional updates.\n * Returns: int\n */\nint f(int a[], int n) {\n    int x = a[0];  // start with the first element as the best candidate\n    for (int i = 1; i < n; i++)  // scan the rest of the array\n        if (a[i] > x)  // compare current element with the best so far\n            x = a[i];  // update best when a[i] is larger\n    return x;\n}\n\n/**\n * Function: g\n * Summary: Finds the minimum element.\n * Inputs: int a[], int n\n * Process: Iterates through elements in a loop, applying conditional updates.\n * Returns: int\n */\nint g(int a[], int n) {\n    int x = a[0];  // start with the first element as the best candidate\n    for (int i = 1; i < n; i++)  // scan the rest of the array\n        if (a[i] < x)  // compare current element with the best so far\n            x = a[i];  // update best when a[i] is smaller\n    return x;  // return the maximum value found\n}\n\n/**\n * Function: h\n * Summary: Recursively sums the last element with the sum of the rest of the array.\n * Inputs: int a[], int n\n * Process: Checks the base case and recursively processes the remaining elements.\n * Returns: int\n */\nint h(int a[], int n) {\n    if (n == 0)  // Base case: empty array yields 0\n        return 0;\n    return a[n - 1] + h(a, n - 1);  // Recursive step: add current element to the sum of the rest of the array\n}\n\n/**\n * Function: k\n * Summary: Combines these three results.\n * Inputs: int a[], int n\n * Process: Calls f, g, h to compute intermediate values and combines their results.\n * Returns: int\n */\nint k(int a[], int n) {\n    int x = f(a, n);  // Compute f(a, n) – this is the first operation in k\n    int y = g(a, n);  // Compute g(a, n) – second operation in k\n    int z = h(a, n);  // Compute h(a, n) – third operation in k\n    return x - y + z;  // Combine results with a simple arithmetic expression\n}",
  "explanation": "Purpose: Computes an expression over an integer array.\nInput: `int a[]` – array to process; `int n` – length.\nOutput: `int` – combined result.\nAlgorithm: `f` finds maximum, `g` finds minimum, `h` recursively sums array, `k` computes f - g + h.",
  "needs_review": false,
  "review_reasons": []
}
```

#### Saving History
To associate the analysis with an authenticated user account, pass the Bearer token:
```text
Authorization: Bearer <session-token>
```

#### cURL
```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "code": "int f(int a[], int n) {\n    int x = a[0];\n    for (int i = 1; i < n; i++)\n        if (a[i] > x) x = a[i];\n    return x;\n}",
    "output_language": "english"
  }'
```

---

## 4. Code Optimization & Recursion-to-Loop Conversion

### `POST /optimize`
Transforms recursive or suboptimal C++ code into verified iterative implementations (using stacks, loops, or dynamic programming). The backend validates semantic equivalence by compiling both original and transformed functions and executing them against test inputs.

#### Request Body
```json
{
  "code": "int sum(int n) {\n    if (n <= 0) return 0;\n    return n + sum(n - 1);\n}",
  "mode": "iterate",
  "source": "web"
}
```

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `code` | string | Yes | — | C++ source code to optimize. |
| `mode` | string | No | `"optimize"` | `"iterate"` (convert recursion to loop/stack) or `"optimize"` (general speedup). |
| `source` | string | No | `"web"` | Set to `"web"` for playground testing without authentication, or provide `Authorization` header. |

#### Response (`200 OK`)
```json
{
  "input_code": "int sum(int n) {\n    if (n <= 0) return 0;\n    return n + sum(n - 1);\n}",
  "code": "int sum(int n) {\n    // Base case: check termination\n    if (n <= 0)\n        return 0;\n\n    int acc = 0;\n    // Iterative replacement of recursion using loop\n    while (n > 0) {\n        acc += n;\n        n--;\n    }\n    return acc;\n}",
  "changed": true,
  "verified": true,
  "speedup": 1.45,
  "note": "Recursion converted to loop; verified equivalent on 8 test inputs (1.5x faster)"
}
```

#### cURL
```bash
curl -s -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "code": "int sum(int n) {\n    if (n <= 0) return 0;\n    return n + sum(n - 1);\n}",
    "mode": "iterate",
    "source": "web"
  }'
```

---

## 5. User Authentication & History

### `POST /auth/register`
Creates a new user account.

#### Request Body
```json
{
  "name": "Jane Developer",
  "email": "jane@example.com",
  "password": "Password123!",
  "confirmPassword": "Password123!"
}
```

#### Response (`200 OK`)
```json
{
  "user": {
    "id": 1,
    "name": "Jane Developer",
    "email": "jane@example.com"
  },
  "token": "d1c2...session_token"
}
```

---

### `POST /auth/login`
Authenticates with email and password to receive a session token.

#### Request Body
```json
{
  "email": "jane@example.com",
  "password": "Password123!"
}
```

#### Response (`200 OK`)
```json
{
  "user": {
    "id": 1,
    "name": "Jane Developer",
    "email": "jane@example.com"
  },
  "token": "d1c2...session_token"
}
```

---

### `GET /auth/me`
Retrieves profile information for the token holder.

#### Headers
```text
Authorization: Bearer <session_token>
```

#### Response (`200 OK`)
```json
{
  "id": 1,
  "name": "Jane Developer",
  "email": "jane@example.com"
}
```

---

### `POST /auth/logout`
Revokes the session token.

#### Headers
```text
Authorization: Bearer <session_token>
```

#### Response (`200 OK`)
```json
{
  "message": "Logged out successfully"
}
```

---

### `GET /analyze/history`
Retrieves past analysis submissions for the authenticated user.

#### Query Parameters
- `limit`: Number of items per page (default: `20`, min: `1`, max: `100`).
- `offset`: Number of items to skip (default: `0`).

#### Headers
```text
Authorization: Bearer <session_token>
```

#### Response (`200 OK`)
```json
{
  "items": [
    {
      "id": 12,
      "input_code": "int add(int a, int b) { return a + b; }",
      "commented_code": "/** ... */\nint add(int a, int b) { ... }",
      "explanation": "Purpose: Adds two numbers.",
      "created_at": "2026-10-03T14:10:00Z",
      "source": "web"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

## 6. Client Code Implementations

### JavaScript / TypeScript (`fetch`)
```javascript
async function analyzeCppCode(cppCode, convertRecursionToLoop = false) {
  // Step 1: Validate syntax
  const valRes = await fetch("http://localhost:8000/validate-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: cppCode })
  });
  const valData = await valRes.json();
  if (!valData.valid) {
    throw new Error(valData.message);
  }

  // Step 2: Analyze code (comments & docstrings)
  const analyzeRes = await fetch("http://localhost:8000/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code: cppCode,
      output_language: "english",
      source: "web"
    })
  });
  const analysis = await analyzeRes.json();

  // Step 3 (Optional): Convert recursion to iterative loop
  if (convertRecursionToLoop) {
    const optRes = await fetch("http://localhost:8000/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: cppCode,
        mode: "iterate",
        source: "web"
      })
    });
    analysis.optimization = await optRes.json();
  }

  return analysis;
}
```

### Python (`requests`)
```python
import requests

BASE_URL = "http://localhost:8000"

code = """
int sumArray(int a[], int n) {
    if (n <= 0) return 0;
    return a[n - 1] + sumArray(a, n - 1);
}
"""

# 1. Check syntax
val = requests.post(f"{BASE_URL}/validate-code", json={"code": code}).json()
if not val.get("valid"):
    print("Syntax Error:", val.get("message"))
    exit(1)

# 2. Analyze code
res = requests.post(
    f"{BASE_URL}/analyze",
    json={"code": code, "output_language": "english", "source": "web"},
).json()

print("--- Commented Code ---")
print(res.get("commented_code"))
print("\n--- Explanation ---")
print(res.get("explanation"))

# 3. Recursion to loop optimization
opt = requests.post(
    f"{BASE_URL}/optimize",
    json={"code": code, "mode": "iterate", "source": "web"},
).json()

print("\n--- Optimized Code ---")
print(opt.get("code"))
print("Verified Equivalent:", opt.get("verified"))
```

### Dart / Flutter
```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

Future<Map<String, dynamic>> analyzeCode(String code) async {
  final url = Uri.parse('http://10.0.2.2:8000/analyze'); // Android emulator host
  final response = await http.post(
    url,
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode({
      'code': code,
      'output_language': 'english',
      'source': 'mobile',
    }),
  );

  if (response.statusCode == 200) {
    return jsonDecode(response.body) as Map<String, dynamic>;
  } else {
    throw Exception('Analysis failed: ${response.body}');
  }
}
```
