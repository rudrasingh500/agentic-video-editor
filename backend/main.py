from fastapi import FastAPI
import uvicorn
from handlers.health_handler import router as health_router

app = FastAPI(app_name="Agent Editor Backend")


app.include_router(health_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)