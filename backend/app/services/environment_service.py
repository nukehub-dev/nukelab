"""
Environment template service for business logic.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.environment_template import EnvironmentTemplate
from app.core.permissions import Permission
from app.dependencies import has_permission


class EnvironmentService:
    """Environment template business logic"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, env_id: str) -> Optional[EnvironmentTemplate]:
        """Get environment by ID"""
        result = await self.db.execute(
            select(EnvironmentTemplate).where(EnvironmentTemplate.id == uuid.UUID(env_id))
        )
        return result.scalar_one_or_none()
    
    async def get_by_slug(self, slug: str) -> Optional[EnvironmentTemplate]:
        """Get environment by slug"""
        result = await self.db.execute(
            select(EnvironmentTemplate).where(EnvironmentTemplate.slug == slug)
        )
        return result.scalar_one_or_none()
    
    async def list_environments(
        self,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """List environments with filtering and pagination"""
        
        query = select(EnvironmentTemplate)
        
        # Apply filters
        filters = []
        if category:
            filters.append(EnvironmentTemplate.category == category)
        if is_active is not None:
            filters.append(EnvironmentTemplate.is_active == is_active)
        if search:
            filters.append(
                or_(
                    EnvironmentTemplate.name.ilike(f"%{search}%"),
                    EnvironmentTemplate.description.ilike(f"%{search}%")
                )
            )
        
        if filters:
            query = query.where(and_(*filters))
        
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()
        
        # Pagination
        query = query.order_by(EnvironmentTemplate.category, EnvironmentTemplate.name)
        query = query.offset((page - 1) * limit).limit(limit)
        
        result = await self.db.execute(query)
        environments = result.scalars().all()
        
        return {
            "items": [env.to_dict() for env in environments],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
    
    async def create_environment(
        self,
        name: str,
        slug: str,
        image: str,
        description: Optional[str] = None,
        dockerfile: Optional[str] = None,
        packages: Optional[List[str]] = None,
        environment_variables: Optional[Dict[str, str]] = None,
        volumes: Optional[List[Dict]] = None,
        ports: Optional[List[int]] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        category: Optional[str] = None,
        is_public: bool = True,
        created_by: Optional[str] = None
    ) -> EnvironmentTemplate:
        """Create new environment template"""
        
        # Check for duplicate slug
        existing = await self.get_by_slug(slug)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Environment with slug '{slug}' already exists"
            )
        
        env = EnvironmentTemplate(
            name=name,
            slug=slug,
            description=description,
            image=image,
            dockerfile=dockerfile,
            packages=packages or [],
            environment_variables=environment_variables or {},
            volumes=volumes or [],
            ports=ports or [],
            icon=icon or "🖥️",
            color=color or "#3B82F6",
            category=category or "base",
            is_public=is_public,
            created_by=uuid.UUID(created_by) if created_by else None
        )
        
        self.db.add(env)
        await self.db.commit()
        await self.db.refresh(env)
        
        return env
    
    async def update_environment(
        self,
        env_id: str,
        **updates
    ) -> EnvironmentTemplate:
        """Update environment template"""
        
        env = await self.get_by_id(env_id)
        if not env:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environment not found"
            )
        
        # Update fields
        for key, value in updates.items():
            if hasattr(env, key) and value is not None:
                setattr(env, key, value)
        
        env.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(env)
        
        return env
    
    async def deactivate_environment(self, env_id: str) -> EnvironmentTemplate:
        """Deactivate environment"""
        return await self.update_environment(env_id, is_active=False)
    
    async def activate_environment(self, env_id: str) -> EnvironmentTemplate:
        """Activate environment"""
        return await self.update_environment(env_id, is_active=True)
    
    async def delete_environment(self, env_id: str) -> None:
        """Permanently delete environment"""
        env = await self.get_by_id(env_id)
        if not env:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environment not found"
            )
        
        await self.db.delete(env)
        await self.db.commit()
    
    async def clone_environment(self, env_id: str, new_name: str, new_slug: str) -> EnvironmentTemplate:
        """Clone an existing environment"""
        
        source = await self.get_by_id(env_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source environment not found"
            )
        
        return await self.create_environment(
            name=new_name,
            slug=new_slug,
            image=source.image,
            description=source.description,
            dockerfile=source.dockerfile,
            packages=source.packages,
            environment_variables=source.environment_variables,
            volumes=source.volumes,
            ports=source.ports,
            icon=source.icon,
            color=source.color,
            category=source.category,
            is_public=source.is_public,
            created_by=str(source.created_by) if source.created_by else None
        )
