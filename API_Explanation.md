# APIs Explained Like You're 10 Years Old! 🎮

## What is an API?

Imagine you go to a restaurant 🍔

- **You** = A computer or phone app
- **The Menu** = The API (a list of things you can ask for)
- **The Kitchen** = The server (where the magic happens)
- **The Waiter** = The API (delivers your request and brings back food)

You don't need to know how the kitchen cooks the food! You just tell the waiter what you want, and they bring it back to you.

**That's exactly what an API does!**

---

## How Does It Work in This Project?

This project has **2 main menus** (API groups):

### 1️⃣ Auth Menu (User Management)

| What You Ask For | What It Does |
|------------------|---------------|
| `POST /auth/register` | Creates a new user account 👤 |
| `POST /auth/login` | Logs you in, gives you a ticket 🎫 |
| `GET /auth/me` | Shows who you are 👀 |
| `POST /auth/logout` | Gives back your ticket 🚪 |

### 2️⃣ Analyze Menu (Code Helper)

| What You Ask For | What It Does |
|------------------|---------------|
| `POST /analyze` | Takes your code and adds helpful comments + explains it 📝 |
| `GET /analyze/history` | Shows your past code analyses 📚 |

---

## Why Do We Use APIs?

### 🔐 **Security**
- You need a ticket (login) to use some features
- Without a ticket, the API says "Nope! 🚫"

### ⚡ **Speed**
- Apps can talk to servers super fast
- No need to install everything on your phone

### 🔄 **Reusability**
- One API can serve many apps (website, mobile, desktop)
- Like one kitchen can feed many restaurants!

### 🛠️ **Separation of Concerns**
- The frontend (what you see) is separate from the backend (logic)
- Like the waiter is separate from the chef

---

## What Problems Do APIs Solve?

| Problem | Solution with API |
|---------|-------------------|
| Apps can't talk to each other | APIs provide a common language 🗣️ |
| Security risks | APIs can check tickets/tokens first 🔒 |
| Hard to update apps | Just update the server, everyone gets the new version 📡 |
| Messy code | Each part does one job, clean and simple 🧹 |

---

## Real-Life Example

**You want to analyze your Python code! 🎯**

1. Your app sends a request to `/analyze`
2. The API receives it, checks your login ticket
3. Sends your code to the "kitchen" (AI model)
4. The AI adds comments and explanations
5. The API brings back the result to you
6. Your history is saved automatically!

**You don't know HOW the AI works. You just get the result!** 🎉

---

## Summary for a 10-Year-Old

> **API = A waiter that takes your order, brings it to the kitchen, and brings back your food.**

- APIs let different programs talk to each other
- They keep things safe and organized
- They make apps faster and easier to build

---

## Want to Try It?

You can use tools like **Postman** or **curl** to talk to these APIs:

```bash
# Example: Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "kid", "password": "secret123"}'
```

That's it! You've now learned what APIs are! 🎉










1️⃣ Users Table
┌────────────┬─────────────────────┐
│ Column     │ What It Stores     │
├────────────┼─────────────────────┤
│ id         │ Unique ID number   │
│ name       │ User's name        │
│ email      │ User's email       │
│ password_salt │ Random characters│
│ password_hash │ Hashed password  │
│ created_at │ When account made  │
└────────────┴─────────────────────┘
---
2️⃣ Sessions Table
┌────────────┬─────────────────────┐
│ Column     │ What It Stores     │
├────────────┼─────────────────────┤
│ id         │ Unique ID          │
│ user_id    │ Links to users     │
│ token      │ The login ticket   │
│ created_at │ When logged in     │
│ expires_at │ When it expires    │
└────────────┴─────────────────────┘
---
3️⃣ Analysis_History Table
┌────────────┬─────────────────────┐
│ Column     │ What It Stores     │
├────────────┼─────────────────────┤
│ id         │ Unique ID          │
│ user_id    │ Links to users     │
│ input_code │ Original code      │
│ commented_code │ Code with AI comments │
│ explanation │ AI explanation   │
│ source     │ Where code came from│
│ created_at │ When analyzed      │
└────────────┴─────────────────────┘