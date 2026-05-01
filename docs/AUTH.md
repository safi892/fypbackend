# Auth and Database

## SQLite schema

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
```

## What is stored

- `users` stores account data
- `password_salt` and `password_hash` protect passwords
- `sessions` stores login tokens

## What Android should store

Android should store only the session token locally. Do not store the full database on the device.

Recommended local cache:

```kotlin
data class SessionCache(
    val token: String,
    val userId: Int,
    val name: String,
    val email: String
)
```

Use DataStore or encrypted shared preferences for the token.
