# Android History Guide

This document explains how to show analysis history in your Android app using the API.

## Prerequisites
- You already have a valid access token from the login endpoint.
- Your app stores the token securely (e.g. EncryptedSharedPreferences).

## Endpoint
- Method: GET
- URL: /analyze/history
- Auth: Authorization: Bearer <token>
- Query params:
  - limit: number of items (1..100), default 20
  - offset: pagination offset, default 0

## Example request (curl)

curl -X GET "http://<HOST>:<PORT>/analyze/history?limit=20&offset=0" \
  -H "Authorization: Bearer <TOKEN>"

## Response shape

{
  "items": [
    {
      "id": 123,
      "input_code": "...",
      "commented_code": "...",
      "explanation": "...",
      "source": "android",
      "created_at": "2026-05-01T10:00:00+00:00"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}

## Kotlin example (Retrofit)

// Data models

data class HistoryEntry(
    val id: Int,
    val input_code: String,
    val commented_code: String,
    val explanation: String,
    val source: String?,
    val created_at: String
)

data class HistoryListResponse(
    val items: List<HistoryEntry>,
    val total: Int,
    val limit: Int,
    val offset: Int
)

// API interface

interface ApiService {
    @GET("/analyze/history")
    suspend fun getHistory(
        @Header("Authorization") bearerToken: String,
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0
    ): HistoryListResponse
}

// Usage

val token = "<TOKEN>"
val response = api.getHistory(
    bearerToken = "Bearer $token",
    limit = 20,
    offset = 0
)

// Render in UI
// response.items contains the history list

## UI Tips
- Show input_code, explanation, and created_at in the list.
- When a row is tapped, open a detail screen and show commented_code.
- Use paging: offset += limit when user scrolls to the bottom.

## Error handling
- 401: token missing/expired -> re-login.
- 503: model unavailable -> show retry UI.
