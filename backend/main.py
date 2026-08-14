"""FastAPI application: serves the dashboard and streams the simulation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.api.routes import router
from backend.config import BASE_DIR, HAS_API_KEY, MODEL_NAME
from backend.db import init_db
from backend.simulation.bus import bus
from backend.simulation.engine import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Reality Simulator", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"model_name": MODEL_NAME, "has_api_key": HAS_API_KEY},
    )


@app.get("/contact", response_class=HTMLResponse)
async def contact_form(request: Request) -> HTMLResponse:
    """The public side of the company: where a message comes in from."""
    return templates.TemplateResponse(request=request, name="contact.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Push every simulation event to the dashboard as it happens (§10)."""
    await websocket.accept()
    queue = bus.subscribe()
    try:
        # Replay the current run so a refresh mid-simulation redraws correctly.
        await websocket.send_text(bus.encode({
            "kind": "snapshot", "seq": 0, "at": "", "simulation": engine.snapshot(),
        }))
        for event in bus.history():
            await websocket.send_text(bus.encode(event))

        while True:
            event = await queue.get()
            await websocket.send_text(bus.encode(event))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except RuntimeError:
        pass
    finally:
        bus.unsubscribe(queue)
