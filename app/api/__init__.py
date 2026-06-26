from fastapi import APIRouter

from app.api.batches import router as batches_router
from app.api.forms import router as forms_router

api_router = APIRouter()
api_router.include_router(batches_router, prefix="/batches", tags=["batches"])
api_router.include_router(forms_router, prefix="/batches", tags=["forms"])
