import httpx
import asyncio

async def test():
    async with httpx.AsyncClient() as client:
        # First register/login to get token
        login_res = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": "test@test.com",
            "password": "password123"
        })
        if login_res.status_code != 200:
            print("Login failed:", login_res.text)
            return
        
        token = login_res.json()["access_token"]
        print("Logged in successfully. Token obtained.")
        
        # Call suggestions
        res = await client.get(
            "http://localhost:8000/api/v1/intelligence/suggestions?suggestion_type=personalized",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0
        )
        print("Suggestions API Status:", res.status_code)
        print("Suggestions API Response:", res.text)

asyncio.run(test())
