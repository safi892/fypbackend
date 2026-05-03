# API Interview Questions 👨‍🏫

---

## Round 1: Basics

### Q1: What is an API?

**Answer:** API is like a waiter in a restaurant - it takes your order (request) from your table (app), delivers it to the kitchen (server), and brings back the food (response) to you. It acts as a bridge between different software systems.

---

### Q2: Why do we use APIs instead of putting all code in one place?

**Answer:** APIs provide separation of concerns. The frontend (what users see) and backend (server logic) can be developed separately. This makes code easier to maintain, scale, and reuse - one API can serve many different apps (mobile, web, desktop).

---

### Q3: What does `POST` mean vs `GET`?

**Answer:** 
- `GET` = Retrieve data from the server (like reading a webpage)
- `POST` = Send data to create or update something (like submitting a form, logging in)

---

## Round 2: Authentication

### Q4: What is the purpose of `/auth/login`?

**Answer:** It verifies the user's credentials (email and password), and if correct, creates a new session with a token so the user stays logged in for future requests.

---

### Q5: How is a password stored in the database? (Don't say "as plain text!")

**Answer:** Passwords are never stored as plain text. They are processed through two steps:
1. **Salt** - Random characters added to password
2. **Hash** - Converted using PBKDF2 with SHA256 algorithm

This makes it impossible to reverse-engineer the actual password.

---

### Q6: What is a token and how is it created?

**Answer:** A token is a unique random string that represents a logged-in session. It's created using `secrets.token_urlsafe(32)` which generates a 32-character cryptographically strong random string. It's then stored in the sessions table linked to the user.

---

### Q7: How does the server know who you are when you make a request?

**Answer:** The client sends an `Authorization` header with the token (e.g., `Bearer abc123...`). The server:
1. Extracts the token from the header
2. Looks up the token in the sessions table
3. Finds the associated user ID
4. Returns the user's data

---

### Q8: What happens if your token expires?

**Answer:** If the token's `expires_at` time has passed, the server returns a 401 "Session expired" error. The user must log in again to get a new token.

---

### Q9: Difference between `/auth/me` and `/auth/login`?

**Answer:** 
- `/auth/login` - Creates a NEW session token (only when user enters credentials)
- `/auth/me` - Just READS existing session to check who you are (uses current token)

---

## Round 3: Database

### Q10: How many tables are in this project?

**Answer:** There are 3 tables:
1. `users` - Stores user accounts
2. `sessions` - Stores login tokens
3. `analysis_history` - Stores past code analyses

---

### Q11: What is the relationship between users and sessions tables?

**Answer:** It's a **one-to-many** relationship. One user can have multiple sessions (logged in on multiple devices at the same time), but each session belongs to only one user.

---

### Q12: Why use `FOREIGN KEY`?

**Answer:** FOREIGN KEY ensures data integrity. It prevents "orphan" records - you can't have a session or history record for a user that doesn't exist. If a user is deleted, related records can be automatically deleted (ON DELETE CASCADE).

---

### Q13: What do indexes do? (hint: look at analysis_history indexes)

**Answer:** Indexes speed up database searches. Without indexes, the database scans every row. With indexes on `user_id` and `created_at`, lookups are much faster - like using a book's index instead of reading every page.

---

## Round 4: Analyze API

### Q14: What does `/analyze` endpoint do?

**Answer:** It takes user's code as input, sends it to an AI model, which adds helpful comments and explanations to the code, and returns the result (commented code + explanation).

---

### Q15: Why do we save history after every analysis?

**Answer:** So users can view their past analyses later. They can review previous code explanations, search through their history, or re-use previous work.

---

### Q16: What is the flow when you call `/analyze`? (step by step)

**Answer:**
1. Server receives request with code + token
2. Validates token (is user logged in?)
3. Sends code to AI model
4. AI returns commented code + explanation
5. Server saves to analysis_history table
6. Returns response to client

---

## Round 5: Security

### Q17: Why is password hashed before storing?

**Answer:** If the database is ever leaked, attackers cannot see or use the actual passwords. Hashing is one-way - you can't convert hash back to original password. This protects users who might use the same password on other sites.

---

### Q18: What would happen if someone sends a request without a token to `/analyze`?

**Answer:** The server returns a 401 error with message "Missing authorization token". The request is rejected because the server can't identify who is making the request.

---

### Q19: How does `Authorization: Bearer <token>` header work?

**Answer:** 
- "Bearer" is the authentication scheme (type)
- The token that follows is the actual session identifier
- Server splits the header, extracts the token, validates it in the database, and identifies the user

---

## Round 6: Advanced

### Q20: What is the difference between 200, 401, and 503 HTTP status codes?

**Answer:**
- **200** = Success - Request completed normally
- **401** = Unauthorized - Invalid or missing token
- **503** = Service Unavailable - Server can't handle request (e.g., AI model not loaded)

---

### Q21: Why use `secrets.token_urlsafe(32)` for tokens?

**Answer:** It generates a cryptographically strong random string that is nearly impossible to guess or crack. Using a simple random number would be unsafe - attackers could guess tokens and hijack sessions.

---

### Q22: What is the purpose of `SESSION_TTL_HOURS`?

**Answer:** TTL stands for "Time To Live". It sets how long a token lasts before expiring (default 24 hours). This is a security measure - even if someone steals a token, they can only use it for a limited time.

---

### Q23: Why do we need both `salt` and `hash` for passwords?

**Answer:** 
- **Salt** - Random data added before hashing - makes same password produce DIFFERENT hash each time
- **Hash** - The result after processing

Without salt, attackers could use "rainbow tables" to reverse common passwords. With unique salt per user, each password hash is unique and much harder to crack.

---

## Challenge Question

### Q24: If a user is logged in on 3 devices, how many session records exist in the database?

**Answer:** 3 session records - one for each device. Each device gets its own unique token.

---

### Q25: If user deletes their account, what happens to their history?

**Answer:** With `ON DELETE CASCADE` in the FOREIGN KEY, all their sessions and analysis history are automatically deleted too. The user and all their data are completely removed.

---

## Score Yourself

| Score | Grade |
|-------|-------|
| 20-25 | 🌟 Expert |
| 15-19 | 🎯 Great |
| 10-14 | 👍 Good |
| 5-9 | 📚 Keep Learning |
| 0-4 | 🔄 Review Again |

---

*Good luck! 🎓*