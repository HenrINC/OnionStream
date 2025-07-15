# Stage 1: Build everything statically
FROM alpine:edge 
#AS builder

RUN apk add --no-cache \
    curl \
    cmake make g++ git \
    ffmpeg-dev \
    hiredis-dev 

RUN git clone https://github.com/sewenew/redis-plus-plus && \
    mkdir redis-plus-plus/build && \
    cd redis-plus-plus/build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DREDIS_PLUS_PLUS_STATIC=ON && \
    make && make install

RUN mkdir -p /demo && \
    curl -L https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4 -o /demo/bigbuckbunny.mp4

WORKDIR /app
COPY main.cpp /app
RUN g++ -std=c++17 main.cpp -lavformat -lavcodec -lavutil -lhiredis -lredis++ -o transcoder

# FROM alpine:edge
# COPY --from=builder /app/transcoder /usr/local/bin/transcoder
CMD ["./transcoder"]
