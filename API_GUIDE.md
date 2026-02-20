# API Guide - Chatbot Backend

## Overview

This document provides a comprehensive guide to the Chatbot Backend API, including authentication, endpoints, and usage examples.

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

The API uses JWT (JSON Web Tokens) for authentication. All protected endpoints require a valid JWT token in the `Authorization` header.

### Header Format

```
Authorization: Bearer <your_jwt_token>
```

## Authentication Endpoints

### 1. Login

**Endpoint:** `POST /auth/login`

**Description:** Authenticate with email and password, receive a JWT access token.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": 1
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'
```

**Python Example:**
```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/auth/login",
    json={
        "email": "user@example.com",
        "password": "password123"
    }
)
token = response.json()["access_token"]
```

### 2. Register

**Endpoint:** `POST /auth/register`

**Description:** Register a new user account and receive a JWT access token.

**Request Body:**
```json
{
  "email": "newuser@example.com",
  "password": "securepassword123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": 2
}
```

**Error Response (409 Conflict):**
```json
{
  "error": "CONFLICT",
  "message": "Email already registered",
  "details": {}
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@example.com",
    "password": "securepassword123"
  }'
```

### 3. Verify Token

**Endpoint:** `GET /auth/verify`

**Description:** Verify that a token is valid (requires authentication).

**Headers:**
```
Authorization: Bearer <your_jwt_token>
```

**Response (200 OK):**
```json
{
  "message": "Token is valid"
}
```

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/api/v1/auth/verify" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## User Endpoints

### 1. List All Users

**Endpoint:** `GET /users/`

**Description:** Get a list of all users (public, no authentication required).

**Response (200 OK):**
```json
{
  "users": []
}
```

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/api/v1/users/"
```

### 2. Get User by ID

**Endpoint:** `GET /users/{user_id}`

**Description:** Get a specific user by their ID (public endpoint).

**Path Parameters:**
- `user_id` (integer): The ID of the user to retrieve

**Response (200 OK):**
```json
{
  "user_id": 1,
  "name": "User 1"
}
```

**Error Response (422 Unprocessable Entity):**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "user_id must be a positive integer",
  "details": {"user_id": -1}
}
```

**Error Response (404 Not Found):**
```json
{
  "error": "RESOURCE_NOT_FOUND",
  "message": "User not found (ID: 999)",
  "details": {"resource": "User", "resource_id": 999}
}
```

**cURL Examples:**
```bash
# Valid request
curl -X GET "http://localhost:8000/api/v1/users/1"

# Invalid ID (negative)
curl -X GET "http://localhost:8000/api/v1/users/-1"

# User not found
curl -X GET "http://localhost:8000/api/v1/users/999"
```

### 3. Create User

**Endpoint:** `POST /users/`

**Description:** Create a new user (public endpoint).

**Request Body:**
```json
{
  "email": "newuser@example.com",
  "username": "newuser"
}
```

**Response (200 OK):**
```json
{
  "user_id": 1,
  "name": "New User"
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/users/" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newuser@example.com",
    "username": "newuser"
  }'
```

### 4. Get Current User Profile

**Endpoint:** `GET /users/me`

**Description:** Get the profile of the currently authenticated user (requires authentication).

**Headers:**
```
Authorization: Bearer <your_jwt_token>
```

**Response (200 OK):**
```json
{
  "user_id": "demo_user_1",
  "sub": "demo_user_1"
}
```

**Error Response (401 Unauthorized):**
```json
{
  "error": "UNAUTHORIZED",
  "message": "Missing authorization header",
  "details": {}
}
```

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/api/v1/users/me" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## Error Handling

The API returns standardized error responses with the following format:

```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable error message",
  "details": {}
}
```

### Common Error Codes

| Code | Status | Description |
|------|--------|-------------|
| VALIDATION_ERROR | 422 | Input validation failed |
| RESOURCE_NOT_FOUND | 404 | Resource not found |
| UNAUTHORIZED | 401 | Authentication required or failed |
| FORBIDDEN | 403 | Permission denied |
| CONFLICT | 409 | Resource already exists |
| DATABASE_ERROR | 500 | Database operation failed |
| SERVICE_UNAVAILABLE | 503 | Service temporarily unavailable |
| INTERNAL_SERVER_ERROR | 500 | Unexpected server error |

## CORS Configuration

The API is configured to accept requests from the following origins:

- `http://localhost`
- `http://localhost:3000` (React/Next.js default)
- `http://localhost:8000` (API itself)
- `http://localhost:8080` (Vue.js default)

To add more origins, update `CORS_ORIGINS` in `app/core/config.py` or set the `CORS_ORIGINS` environment variable.

## Environment Variables

Key configuration variables for the API:

```env
# JWT Configuration
JWT_SECRET=your-secret-key-min-32-chars-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# API Configuration
API_V1_PREFIX=/api/v1
API_TITLE=Chatbot Backend API
API_VERSION=0.1.0

# Database
SQLALCHEMY_DATABASE_URI=postgresql+asyncpg://user:password@localhost:5432/chatbot

# CORS
CORS_ORIGINS=["http://localhost", "http://localhost:3000"]

# Environment
ENVIRONMENT=development
DEBUG=true
```

## Security Best Practices

1. **Always use HTTPS in production** - Never use HTTP with real tokens
2. **Keep JWT_SECRET secure** - Use a strong, randomly generated secret
3. **Rotate tokens regularly** - Implement token refresh mechanism
4. **Validate all inputs** - The API validates input types and formats
5. **Log authentication events** - All auth attempts are logged
6. **Use short expiration times** - Default 24 hours, consider shorter for sensitive operations

## Testing the API

### Using cURL

```bash
# Login
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password"}' \
  | jq -r '.access_token')

# Use token to access protected endpoint
curl -X GET "http://localhost:8000/api/v1/users/me" \
  -H "Authorization: Bearer $TOKEN"
```

### Using Python

```python
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

# Login
login_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"email": "user@example.com", "password": "password"}
)
token = login_response.json()["access_token"]

# Access protected endpoint
headers = {"Authorization": f"Bearer {token}"}
profile = requests.get(f"{BASE_URL}/users/me", headers=headers)
print(profile.json())
```

### Using JavaScript

```javascript
const BASE_URL = "http://localhost:8000/api/v1";

// Login
const loginResponse = await fetch(`${BASE_URL}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    email: "user@example.com",
    password: "password"
  })
});

const { access_token } = await loginResponse.json();

// Access protected endpoint
const profileResponse = await fetch(`${BASE_URL}/users/me`, {
  headers: { "Authorization": `Bearer ${access_token}` }
});

const profile = await profileResponse.json();
console.log(profile);
```

## Interactive Documentation

The API includes interactive API documentation:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

You can test all endpoints directly from your browser using Swagger UI.

## Logging

All requests and errors are logged with structured logging. Log entries include:

- Timestamp (ISO 8601)
- Log level (INFO, WARNING, ERROR)
- Event type
- Path and HTTP method
- Status code
- User ID (for authenticated requests)
- Error code and details (for errors)

Example log entry:

```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "info",
  "event": "User authenticated",
  "path": "/api/v1/users/me",
  "method": "GET",
  "user_id": "demo_user_1"
}
```

## Rate Limiting

Currently, the API does not implement rate limiting. This is planned for a future release.

## Pagination

List endpoints do not currently support pagination. This is planned for a future release.

## Versioning

The API is currently at version 1.0.0. All endpoints are under the `/api/v1/` prefix.

Future versions will be available at `/api/v2/`, etc., while maintaining backward compatibility.