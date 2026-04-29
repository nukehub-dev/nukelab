"""
Seed data for plans only.
Environments are admin-created via the API/Admin panel, not hardcoded.
Run this after database initialization.
"""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import async_session
from app.services.plan_service import PlanService


async def seed_plans(db: AsyncSession):
    """Seed default server plans"""
    service = PlanService(db)
    
    plans = [
        {
            "name": "Small",
            "slug": "small",
            "description": "2 CPU / 4GB — suitable for development, light analysis, and Jupyter notebooks",
            "category": "cpu",
            "cpu_limit": 2.0,
            "memory_limit": "4g",
            "disk_limit": "20g",
            "max_servers_per_user": 4,
            "cost_per_hour": 1,
            "priority": 0,
        },
        {
            "name": "Medium",
            "slug": "medium",
            "description": "4 CPU / 8GB — standard compute for most simulations and data processing",
            "category": "cpu",
            "cpu_limit": 4.0,
            "memory_limit": "8g",
            "disk_limit": "50g",
            "max_servers_per_user": 3,
            "cost_per_hour": 2,
            "priority": 1,
        },
        {
            "name": "Large",
            "slug": "large",
            "description": "8 CPU / 16GB — high-performance for demanding workloads and parallel jobs",
            "category": "cpu",
            "cpu_limit": 8.0,
            "memory_limit": "16g",
            "disk_limit": "100g",
            "max_servers_per_user": 2,
            "cost_per_hour": 4,
            "priority": 2,
        },
        {
            "name": "XLarge",
            "slug": "xlarge",
            "description": "16 CPU / 32GB — maximum resources for heavy computations (admin approval required)",
            "category": "cpu",
            "cpu_limit": 16.0,
            "memory_limit": "32g",
            "disk_limit": "200g",
            "max_servers_per_user": 1,
            "cost_per_hour": 8,
            "priority": 3,
            "requires_approval": True,
            "allowed_roles": ["admin", "super_admin"],
        },
    ]
    
    for plan_data in plans:
        try:
            existing = await service.get_by_slug(plan_data["slug"])
            if not existing:
                await service.create_plan(**plan_data)
                print(f"✓ Created plan: {plan_data['name']}")
            else:
                print(f"  Plan exists: {plan_data['name']}")
        except Exception as e:
            print(f"✗ Failed to create {plan_data['name']}: {e}")


async def seed_all():
    """Seed default data (plans only — environments are admin-created)"""
    async with async_session() as db:
        print("Seeding plans...")
        await seed_plans(db)
        
        print("\n✓ Seeding complete!")
    

if __name__ == "__main__":
    asyncio.run(seed_all())
