import pytest

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import models
from schemas import UserCreate
from services.user_service import UserService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session):
    return UserService(session)


def make_user(username: str = "Geralt", email: str = "GeraltofRivia@example.com", password: str = "fakepassword"):
    return UserCreate(username=username, email=email, password=password)


async def count_user(session):
    return await session.scalar(select(func.count()).select_from(models.User))


async def test_create_user(service, session):
    user = await service.create_user(make_user())

    assert user.id is not None
    assert user.username == "Geralt"
    assert user.email == "geraltofrivia@example.com"
    assert user.hashed_password != "fakepassword"
    assert await count_user(session) == 1


async def test_duplicate_user_is_rejected(service, session):
    await service.create_user(make_user())

    with pytest.raises(HTTPException) as exc:
        await service.create_user(make_user(email="yukiomishima@gmail.com"))

    assert exc.value.status_code == 406
    assert await count_user(session) == 1


async def test_duplicate_email_is_rejected(service, session):
    await service.create_user(make_user())

    with pytest.raises(HTTPException) as exc:
        await service.create_user(make_user(username="Yukio", email="GERALTOFRIVIA@example.com"))

    assert exc.value.status_code == 400
    assert await count_user(session) == 1
