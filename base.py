from fastapi import FastAPI
from settings_bot import router as settings_router
from asking_bot import router as asking_router
import logging

app = FastAPI()
app.include_router(settings_router)
app.include_router(asking_router)

def some_base_function(...):
    logging.info(f"[BASE] some_base_function called with ...")
    # ... existing code ...