import asyncio
from sqlalchemy import select
from app.database.connection import AsyncSessionLocal
from app.models.user import User
from app.api.v1.intelligence import get_suggestions

async def main():
    async with AsyncSessionLocal() as db:
        # Get first user
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users found in database!")
            return
        
        print(f"Testing suggestions for user: {user.email} (ID: {user.id})")
        
        try:
            suggestions = await get_suggestions(suggestion_type="personalized", db=db, current_user=user)
            print("Personalized suggestions successfully generated:")
            print(suggestions)
        except Exception as e:
            print("Error generating personalized suggestions:")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
