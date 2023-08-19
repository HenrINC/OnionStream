import os

from fastapi import FastAPI, Depends, Query
from fastapi.responses import Response
import uvicorn


app = FastAPI()

webserver_port = os.environ.get("WEBSERVER_PORT")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=webserver_port, timeout_keep_alive=60)