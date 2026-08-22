"""Generic repository base class - thin wrapper over SQLAlchemy Session
so services depend on a repository interface rather than the ORM directly."""
from typing import Generic, Type, TypeVar

from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    model: Type[ModelType]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id: int) -> ModelType | None:
        return self.db.query(self.model).filter(self.model.id == id).first()

    def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.commit()

    def commit_refresh(self, obj: ModelType) -> ModelType:
        self.db.commit()
        self.db.refresh(obj)
        return obj
