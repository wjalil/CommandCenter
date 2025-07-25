import requests

token = "eeyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwOGI2YjkyNS1hZmVmLTQ3YzItYjNhYy02ZTNiZWQ3N2UyNDgiLCJhdWQiOiJmYXN0YXBpLXVzZXJzOmF1dGgiLCJleHAiOjE3NTI3MjExMDF9.8uBkrI5mJBrtXMeW0IZYi20XCWlVD2BJqmtkDqHn8JQ"  # Your JWT
headers = {
    "Authorization": f"Bearer {token}"
}

res = requests.get("http://127.0.0.1:8000/whoami", headers=headers)

print("Status Code:", res.status_code)
print("Response:", res.text)
