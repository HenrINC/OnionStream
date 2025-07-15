from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from .routers.debug import router as debug_router
from .routers.stream import router as stream_router

app = FastAPI()

app.include_router(debug_router, prefix="/debug", tags=["debug"])
app.include_router(stream_router, prefix="/stream", tags=["stream"])
app.mount("/static", StaticFiles(directory="/app/static"), name="static")


@app.get("/")
@app.get("/index.html")
async def index():
    return RedirectResponse(url="/static/index.html")
