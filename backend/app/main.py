from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import auth, users, servers, tokens, credits, admin
from app.db.base import Base
from app.db.session import engine

app = FastAPI(
    title=settings.app_name,
    description="NukeLab Platform v2.0 API",
    version="2.0.0",
    debug=settings.app_debug,
    root_path="/api",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_debug else [settings.app_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(servers.router, prefix="/servers", tags=["servers"])
app.include_router(tokens.router, prefix="/tokens", tags=["tokens"])
app.include_router(credits.router, prefix="/credits", tags=["credits"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.on_event("startup")
async def startup():
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.app_name} API", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
