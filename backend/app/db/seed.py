"""
Seed data for environments and plans.
Run this after database initialization.
"""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import async_session
from app.services.environment_service import EnvironmentService
from app.services.plan_service import PlanService


async def seed_environments(db: AsyncSession):
    """Seed default environment templates"""
    service = EnvironmentService(db)
    
    environments = [
        {
            "name": "Base Python",
            "slug": "base",
            "description": "Minimal Python environment with Jupyter support",
            "image": "nukelab/base:latest",
            "category": "base",
            "icon": "🐍",
            "color": "#3B82F6",
            "packages": ["jupyter", "numpy", "pandas", "matplotlib"],
            "environment_variables": {"JUPYTER_ENABLE_LAB": "yes"},
            "ports": [3000, 8888],
        },
        {
            "name": "Neutronics Workbench",
            "slug": "neutronics",
            "description": "OpenMC + DAGMC + MOAB for neutronics simulations",
            "image": "nukelab/neutronics:latest",
            "category": "neutronics",
            "icon": "⚛️",
            "color": "#F97316",
            "packages": ["openmc", "dagmc", "moab", "mcnp", "serpent"],
            "environment_variables": {"OPENMC_CROSS_SECTIONS": "/data/endfb71"},
            "ports": [3000, 8888],
        },
        {
            "name": "Multiphysics Suite",
            "slug": "multiphysics",
            "description": "OpenFOAM + ParaView + FEniCS for multiphysics simulations",
            "image": "nukelab/multiphysics:latest",
            "category": "multiphysics",
            "icon": "🔬",
            "color": "#A855F7",
            "packages": ["openfoam", "paraview", "fenics", "calculix"],
            "environment_variables": {"FOAM_INST_DIR": "/opt/openfoam"},
            "ports": [3000, 8888],
        },
        {
            "name": "Visualization Studio",
            "slug": "visualization",
            "description": "ParaView + VTK + Blender for scientific visualization",
            "image": "nukelab/viz:latest",
            "category": "visualization",
            "icon": "🎨",
            "color": "#EC4899",
            "packages": ["paraview", "vtk", "blender", "matplotlib", "plotly"],
            "environment_variables": {"DISPLAY": ":1"},
            "ports": [3000, 8888, 5900],
        },
        {
            "name": "Development Environment",
            "slug": "dev",
            "description": "Full development stack with VS Code, Git, Docker",
            "image": "nukelab/dev:latest",
            "category": "dev",
            "icon": "💻",
            "color": "#22C55E",
            "packages": ["git", "docker", "nodejs", "typescript", "eslint"],
            "environment_variables": {"DEV_MODE": "true"},
            "ports": [3000, 8080],
        },
    ]
    
    for env_data in environments:
        try:
            existing = await service.get_by_slug(env_data["slug"])
            if not existing:
                await service.create_environment(**env_data)
                print(f"✓ Created environment: {env_data['name']}")
            else:
                print(f"  Environment exists: {env_data['name']}")
        except Exception as e:
            print(f"✗ Failed to create {env_data['name']}: {e}")


async def seed_plans(db: AsyncSession):
    """Seed default server plans"""
    service = PlanService(db)
    
    plans = [
        {
            "name": "Nano",
            "slug": "nano",
            "description": "Minimal resources for quick tasks",
            "category": "cpu",
            "cpu_limit": 0.5,
            "memory_limit": "512m",
            "disk_limit": "5g",
            "max_servers_per_user": 5,
            "cost_per_hour": 5,
            "priority": 0,
        },
        {
            "name": "Micro",
            "slug": "micro",
            "description": "Small resources for testing",
            "category": "cpu",
            "cpu_limit": 1.0,
            "memory_limit": "1g",
            "disk_limit": "10g",
            "max_servers_per_user": 4,
            "cost_per_hour": 10,
            "priority": 1,
        },
        {
            "name": "Small",
            "slug": "small",
            "description": "Standard compute for most tasks",
            "category": "cpu",
            "cpu_limit": 2.0,
            "memory_limit": "4g",
            "disk_limit": "20g",
            "max_servers_per_user": 3,
            "cost_per_hour": 20,
            "priority": 2,
        },
        {
            "name": "Medium",
            "slug": "medium",
            "description": "More power for complex simulations",
            "category": "cpu",
            "cpu_limit": 4.0,
            "memory_limit": "8g",
            "disk_limit": "40g",
            "max_servers_per_user": 2,
            "cost_per_hour": 40,
            "priority": 3,
        },
        {
            "name": "Large",
            "slug": "large",
            "description": "High-performance for demanding workloads",
            "category": "cpu",
            "cpu_limit": 8.0,
            "memory_limit": "16g",
            "disk_limit": "80g",
            "max_servers_per_user": 1,
            "cost_per_hour": 80,
            "priority": 4,
        },
        {
            "name": "XLarge",
            "slug": "xlarge",
            "description": "Maximum resources for heavy computations",
            "category": "cpu",
            "cpu_limit": 16.0,
            "memory_limit": "32g",
            "disk_limit": "160g",
            "max_servers_per_user": 1,
            "cost_per_hour": 160,
            "priority": 5,
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
    """Seed all default data"""
    async with async_session() as db:
        print("Seeding environments...")
        await seed_environments(db)
        
        print("\nSeeding plans...")
        await seed_plans(db)
        
        print("\n✓ Seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed_all())
