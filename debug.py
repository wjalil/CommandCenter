import jwt

# 👇 Paste your JWT token here (without "Bearer " prefix)
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjY1M2FlNC1hYjBhLTQ3ZTEtOWYwYi1lNzM3Mjk0OGVkMjMiLCJhdWQiOlsiZmFzdGFwaS11c2VyczphdXRoIl0sImV4cCI6MTc1MjcwNTY4N30.IC5Kmaven65ug4S7UUtjyYF1ctxi5lxi61GW93euZqI"

# 👇 Use your actual JWT secret from auth_config.secret
secret = "cookieops-super-secret-key"

try:
    decoded = jwt.decode(token, secret, algorithms=["HS256"],audience="fastapi-users:auth")
    print("✅ Token is valid!")
    print("Decoded payload:")
    print(decoded)
except jwt.ExpiredSignatureError:
    print("❌ Token has expired.")
except jwt.InvalidTokenError as e:
    print(f"❌ Invalid token: {e}")
