# Android to Backend Guide

This guide shows the easiest way for the Android developer to send code to the backend and receive the analyzed result.

## 1. Backend API details

Base URL:

```text
http://YOUR_SERVER_IP:8000/
```

Analyze endpoint:

```text
POST /analyze
```

Health check:

```text
GET /health
```

## 2. What Android should send

The Android app only needs to send JSON with one field:

```json
{
  "code": "int add(int a, int b) { if (a > b) return a - b; return a + b; }"
}
```

`source` is optional in the backend request model, but the easiest approach is to ignore it and send only `code`.

## 3. What backend returns

The backend returns JSON in this format:

```json
{
  "input_code": "int add(int a, int b) { if (a > b) return a - b; return a + b; }",
  "commented_code": "// Define the function add\nint add(int a, int b) {\n// Check whether the condition is true before running this block\nif (a > b) return a - b;\n// Return the computed value to the caller\nreturn a + b;\n}",
  "explanation": "The function add processes the given code. It checks conditions to control the flow, returns a result, and performs arithmetic operations."
}
```

Android only needs to read:

- `input_code`
- `commented_code`
- `explanation`

## 4. Recommended Android approach

Use Retrofit. It is the easiest and cleanest option for Android.

## 5. Add dependencies

In Android `build.gradle`:

```gradle
implementation "com.squareup.retrofit2:retrofit:2.11.0"
implementation "com.squareup.retrofit2:converter-gson:2.11.0"
implementation "com.squareup.okhttp3:logging-interceptor:4.12.0"
```

## 6. Create request model

```kotlin
data class AnalyzeRequest(
    val code: String
)
```

## 7. Create response model

```kotlin
data class AnalyzeResponse(
    val input_code: String,
    val commented_code: String,
    val explanation: String
)
```

## 8. Create Retrofit API interface

```kotlin
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST

interface CodeApiService {
    @POST("analyze")
    suspend fun analyzeCode(
        @Body request: AnalyzeRequest
    ): Response<AnalyzeResponse>
}
```

## 9. Create Retrofit instance

```kotlin
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {
    private const val BASE_URL = "http://YOUR_SERVER_IP:8000/"

    private val logging = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BODY
    }

    private val client = OkHttpClient.Builder()
        .addInterceptor(logging)
        .build()

    val api: CodeApiService by lazy {
        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(CodeApiService::class.java)
    }
}
```

## 10. Send code from Android

Use a ViewModel or repository and call the API inside a coroutine:

```kotlin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class CodeRepository {
    suspend fun analyzeCode(code: String): AnalyzeResponse? {
        return withContext(Dispatchers.IO) {
            val response = RetrofitClient.api.analyzeCode(
                AnalyzeRequest(code = code)
            )

            if (response.isSuccessful) {
                response.body()
            } else {
                null
            }
        }
    }
}
```

## 11. Show response in Android UI

After receiving the response:

- show `commented_code` in the code editor or text view
- show `explanation` in a separate explanation section

Example:

```kotlin
val result = repository.analyzeCode(userCode)

if (result != null) {
    codeEditor.setText(result.commented_code)
    explanationTextView.text = result.explanation
} else {
    explanationTextView.text = "Failed to analyze code."
}
```

## 12. Step-by-step flow for the Android developer

1. User writes or pastes code in the Android app.
2. Android reads that code as a string.
3. Android sends a `POST` request to `/analyze`.
4. Request body contains:

```json
{
  "code": "user pasted code here"
}
```

5. Backend analyzes the code.
6. Backend returns JSON with:
   - `input_code`
   - `commented_code`
   - `explanation`
7. Android receives the response.
8. Android displays:
   - `commented_code` in the editor
   - `explanation` below it

## 13. Example cURL test

The Android developer can test the backend first with:

```bash
curl -X POST "http://YOUR_SERVER_IP:8000/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "int add(int a, int b) { if (a > b) return a - b; return a + b; }"
  }'
```

## 14. Important notes

- Android emulator usually cannot use `localhost` for your computer backend.
- If testing with Android emulator, use the actual machine IP, for example:

```text
http://192.168.1.5:8000/
```

- If using the standard Android emulator and backend runs on the same computer, `10.0.2.2` may also work:

```text
http://10.0.2.2:8000/
```

- Make sure backend CORS/network access and firewall allow requests from the Android test device.

## 15. Simplest contract to share with Android developer

Send:

```json
{
  "code": "user code"
}
```

Receive:

```json
{
  "input_code": "...",
  "commented_code": "...",
  "explanation": "..."
}
```

That is all the Android developer needs.
