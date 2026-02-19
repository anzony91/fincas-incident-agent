"""
Providers API Router
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.provider import Provider
from app.models.ticket import Category
from app.schemas import (
    ProviderCreate,
    ProviderListResponse,
    ProviderResponse,
    ProviderUpdate,
)

router = APIRouter()


@router.get("", response_model=ProviderListResponse)
async def list_providers(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    category: Optional[Category] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List providers with pagination and filters"""
    query = select(Provider)
    count_query = select(func.count(Provider.id))
    
    # Apply filters
    if category:
        query = query.where(Provider.category == category)
        count_query = count_query.where(Provider.category == category)
    if is_active is not None:
        query = query.where(Provider.is_active == is_active)
        count_query = count_query.where(Provider.is_active == is_active)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Provider.name.ilike(search_filter)) |
            (Provider.email.ilike(search_filter))
        )
        count_query = count_query.where(
            (Provider.name.ilike(search_filter)) |
            (Provider.email.ilike(search_filter))
        )
    
    # Get total count
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.order_by(Provider.name).offset(offset).limit(size)
    
    result = await db.execute(query)
    providers = result.scalars().all()
    
    return ProviderListResponse(
        items=[ProviderResponse.model_validate(p) for p in providers],
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )


@router.get("/by-category/{category}", response_model=list[ProviderResponse])
async def get_providers_by_category(
    category: Category,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Get all providers for a specific category"""
    query = select(Provider).where(Provider.category == category)
    
    if active_only:
        query = query.where(Provider.is_active == True)  # noqa: E712
    
    query = query.order_by(Provider.is_default.desc(), Provider.name)
    
    result = await db.execute(query)
    providers = result.scalars().all()
    
    return [ProviderResponse.model_validate(p) for p in providers]


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single provider"""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    return ProviderResponse.model_validate(provider)


@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider(
    provider_data: ProviderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new provider"""
    # If setting as default, unset other defaults for this category
    if provider_data.is_default:
        await db.execute(
            select(Provider)
            .where(
                (Provider.category == provider_data.category) &
                (Provider.is_default == True)  # noqa: E712
            )
        )
        result = await db.execute(
            select(Provider).where(
                (Provider.category == provider_data.category) &
                (Provider.is_default == True)  # noqa: E712
            )
        )
        for existing in result.scalars().all():
            existing.is_default = False
    
    provider = Provider(**provider_data.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    
    return ProviderResponse.model_validate(provider)


@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int,
    provider_data: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a provider"""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    update_data = provider_data.model_dump(exclude_unset=True)
    
    # If setting as default, unset other defaults for this category
    if update_data.get("is_default"):
        category = update_data.get("category", provider.category)
        defaults_result = await db.execute(
            select(Provider).where(
                (Provider.category == category) &
                (Provider.is_default == True) &  # noqa: E712
                (Provider.id != provider_id)
            )
        )
        for existing in defaults_result.scalars().all():
            existing.is_default = False
    
    for key, value in update_data.items():
        setattr(provider, key, value)
    
    await db.commit()
    await db.refresh(provider)
    
    return ProviderResponse.model_validate(provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a provider"""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    await db.delete(provider)
    await db.commit()
