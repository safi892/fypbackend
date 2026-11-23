# Android Integration

## Analyze flow

English is the default. Existing clients can still send only `code`:

```json
{ "code": "user code" }
```

To request Roman Urdu, include `output_language`:

```json
{
  "code": "user code",
  "output_language": "roman_urdu"
}
```

Receive:

```json
{
  "input_code": "...",
  "commented_code": "...",
  "explanation": "...",
  "needs_review": false
}
```

When `output_language` is `english`, `commented_code` and `explanation` are
English.

When `output_language` is `roman_urdu`, generated prose is Roman Urdu:

- `explanation` is Roman Urdu
- `commented_code` keeps the submitted C++ unchanged and appends Roman Urdu
  comments
- `needs_review` tells the UI whether comments were dropped or rejected

Do not expect code to be translated. `input_code` and the C++ inside
`commented_code` remain tied to the submitted C++.

`explanation` does not include time complexity or space complexity. Show it as
the short purpose/input/output/algorithm explanation.

## Register flow

Use:

```kotlin
data class RegisterRequest(
    val name: String,
    val email: String,
    val password: String,
    @SerializedName("confirmPassword") val confirmPassword: String
)
```

## Login flow

Use:

```kotlin
data class LoginRequest(
    val email: String,
    val password: String
)
```

## Token storage

Save only the token locally.

Example header when calling protected endpoints:

```kotlin
Authorization: Bearer your-session-token
```

If the token is removed from local storage, treat the user as logged out on the device.

## History & Optimization Flow

To display past reviews in the Documentation screen:

Call `GET /analyze/history?limit=20&offset=0` (or `GET /analyze/history/{id}` for single item detail):

```kotlin
data class HistoryEntry(
    val id: Int,
    @SerializedName("input_code") val inputCode: String,
    @SerializedName("commented_code") val commentedCode: String,
    val explanation: String,
    val source: String?,
    @SerializedName("created_at") val createdAt: String,
    @SerializedName("optimized_code") val optimizedCode: String?,
    @SerializedName("optimization_verified") val optimizationVerified: Boolean?,
    val speedup: Double?,
    @SerializedName("optimization_note") val optimizationNote: String?
)

data class HistoryListResponse(
    val items: List<HistoryEntry>,
    val total: Int,
    val limit: Int,
    val offset: Int
)
```

UI rendering logic:
- If `optimizedCode != null`, render the "Optimized" toggle.
- If `optimizationVerified == true`, render the "Verified" badge.
- If `speedup != null && speedup > 1.0`, render `"⚡ ${speedup}x"`.

## Function-by-Function Breakdown

Both `POST /analyze` and `POST /optimize` now return a `functions: List<...>` array.
This allows the Android app to render horizontal chips (`[ All ] [ calculateTotal ] [ calculateAverage ] ...`) and show isolated documentation, code, and diffs when the user taps a specific function.

### Analyze Function Model

```kotlin
data class DocEntry(
    val function: String,
    val description: String,
    val parameters: List<String>,
    val returns: String
)

data class FunctionAnalysisItem(
    val name: String,
    @SerializedName("start_line") val startLine: Int,
    @SerializedName("end_line") val endLine: Int,
    val code: String,
    @SerializedName("commented_code") val commentedCode: String,
    val documentation: DocEntry?,
    val explanation: String
)

data class AnalyzeResponse(
    @SerializedName("input_code") val inputCode: String,
    @SerializedName("commented_code") val commentedCode: String,
    val explanation: String,
    @SerializedName("needs_review") val needsReview: Boolean,
    val functions: List<FunctionAnalysisItem> = emptyList()
)
```

### Optimize Function Model

```kotlin
data class DiffRow(
    val kind: String, // "context" | "added" | "removed"
    @SerializedName("old_line") val oldLine: Int?,
    @SerializedName("new_line") val newLine: Int?,
    val text: String
)

data class FunctionOptimizationItem(
    val name: String,
    @SerializedName("start_line") val startLine: Int,
    @SerializedName("end_line") val endLine: Int,
    @SerializedName("original_code") val originalCode: String,
    @SerializedName("optimized_code") val optimizedCode: String,
    val changed: Boolean,
    val verified: Boolean,
    val speedup: Double,
    val note: String?,
    val diff: List<DiffRow> = emptyList()
)

data class OptimizeResponse(
    @SerializedName("input_code") val inputCode: String,
    val code: String,
    val changed: Boolean,
    val verified: Boolean,
    val speedup: Double,
    val note: String?,
    val explanation: String,
    val functions: List<FunctionOptimizationItem> = emptyList()
)
```


