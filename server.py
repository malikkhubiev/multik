from loader import app
from fastapi.responses import JSONResponse
from fastapi import Request
from config import PORT
from database import database
import uvicorn
from base import *
from utils import *

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    logging.info("[MIDDLEWARE] Перед database.connect()")
    await database.connect()
    logging.info("[MIDDLEWARE] После database.connect()")
    request.state.db = database
    logging.info("[MIDDLEWARE] Перед call_next")
    response = await call_next(request)
    logging.info("[MIDDLEWARE] После call_next")
    logging.info("[MIDDLEWARE] Перед database.disconnect()")
    await database.disconnect()
    logging.info("[MIDDLEWARE] После database.disconnect()")
    return response

@app.api_route("/", methods=["GET", "HEAD"])
async def super():
    logging.info("[HANDLER] Получен запрос на / (корень)")
    return JSONResponse(content={"message": f"Сервер работает!"}, status_code=200)

if __name__ == "__main__":
    port = int(PORT)
    print("port")
    print(port)
    logging.info(f"[STARTUP] Запуск uvicorn на порту {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
