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
