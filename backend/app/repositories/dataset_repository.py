from .. import models
from .base import BaseRepository


class DatasetRepository(BaseRepository[models.Dataset]):
    model = models.Dataset

    def get_by_id_for_owner(
        self, dataset_id: int, owner_id: int
    ) -> models.Dataset | None:
        return (
            self.db.query(models.Dataset)
            .filter(
                models.Dataset.id == dataset_id, models.Dataset.owner_id == owner_id
            )
            .first()
        )

    def list_for_owner(self, owner_id: int):
        """Unpaginated - preserves the original behavior for existing callers."""
        return (
            self.db.query(models.Dataset)
            .filter(models.Dataset.owner_id == owner_id)
            .order_by(models.Dataset.uploaded_at.desc())
            .all()
        )

    def list_for_owner_paginated(self, owner_id: int, page: int, page_size: int):
        query = (
            self.db.query(models.Dataset)
            .filter(models.Dataset.owner_id == owner_id)
            .order_by(models.Dataset.uploaded_at.desc())
        )
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total
