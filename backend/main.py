from fastapi import FastAPI
import uvicorn
from handlers.health_handler import router as health_router
from handlers.auth_handler import router as auth_router
from handlers.project_handler import router as project_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(app_name="Agent Editor Backend")


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(project_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
