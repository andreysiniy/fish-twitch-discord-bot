from sqlalchemy.orm import Session
from typing import Generic, TypeVar, Type

T = TypeVar("T")

class BaseRepository(Generic[T]):
    def __init__(self, db: Session, model: Type[T]):
        self.db = db
        self.model = model

    def get_by_id(self, id: int) -> T | None:
        return self.db.query(self.model).filter(self.model.id == id).first()

    def save(self, obj: T) -> T:
        self.db.add(obj)
        self.db.flush()
        self.db.refresh(obj)
        return obj
