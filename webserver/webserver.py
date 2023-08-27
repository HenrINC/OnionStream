import os

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
import uvicorn


class CSPMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def inner_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                csp_header = (
                    "content-security-policy",
                    "default-src 'self'; media-src 'self' blob: data:; connect-src 'self' blob: data:;",
                )
                headers.append(csp_header)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, inner_send)


app = FastAPI()

app.add_middleware(CSPMiddleware)

webserver_port = os.environ.get("WEBSERVER_PORT")

app.mount("/pages", StaticFiles(directory="pages"), name="pages")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=webserver_port, timeout_keep_alive=60)
