FROM node:24-alpine3.21 AS font_builder

# Create working directory
WORKDIR /front_builder

# Copy and install dependencies
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --no-audit --no-fund && npm cache clean --force

# Install esbuild globally
RUN npm install -g esbuild

# Create static output dir
RUN mkdir -p /app/static/h264decoder

# Bundle h264decoder for browser using esbuild
RUN esbuild node_modules/h264decoder/dist/index.js \
    --bundle \
    --format=iife \
    --global-name=H264DecoderModule \
    --outfile=/app/static/h264decoder/bundle.js

# Copy remaining static assets
COPY frontend/index.html frontend/main.js frontend/debug.html /app/static/

FROM python:3.13-alpine3.21

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=font_builder /app/static /app/static

COPY backend/app ./webserver

CMD ["uvicorn", "webserver.main:app", "--host", "0.0.0.0", "--port", "80"]
