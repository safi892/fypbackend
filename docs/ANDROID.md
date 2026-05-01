# Android Integration

## Analyze flow

Send only:

```json
{ "code": "user code" }
```

Receive:

```json
{
  "input_code": "...",
  "commented_code": "...",
  "explanation": "..."
}
```

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
