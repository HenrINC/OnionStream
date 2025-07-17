#include <iostream>
#include <string>
#include <chrono>
#include <thread>
#include <unordered_map>
#include <sw/redis++/redis++.h>

extern "C"
{
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libavutil/avutil.h>
#include <libswscale/swscale.h>
}

using namespace sw::redis;

void parse_nal(const uint8_t *data, size_t size)
{
    // Search for start code prefix (00 00 01 or 00 00 00 01)
    size_t offset = 0;
    while (offset + 4 < size)
    {
        if (data[offset] == 0x00 && data[offset + 1] == 0x00)
        {
            if (data[offset + 2] == 0x01)
            {
                offset += 3;
                break;
            }
            else if (data[offset + 2] == 0x00 && data[offset + 3] == 0x01)
            {
                offset += 4;
                break;
            }
        }
        offset++;
    }

    if (offset >= size)
    {
        std::cerr << "No NAL start code found.\n";
        return;
    }

    if (offset >= size - 1)
    {
        std::cerr << "Not enough data after start code to parse NAL header.\n";
        return;
    }

    uint8_t header = data[offset];
    uint8_t forbidden_zero_bit = (header >> 7) & 0x01;
    uint8_t nri = (header >> 5) & 0x03;
    uint8_t nal_type = header & 0x1F;

    // std::cout << "NAL header: 0x" << std::hex << int(header) << std::dec << "\n";
    // std::cout << "  forbidden_zero_bit: " << int(forbidden_zero_bit) << "\n";
    // std::cout << "  nal_ref_idc: " << int(nri) << "\n";
    // std::cout << "  nal_unit_type: " << int(nal_type) << "\n";

    switch (nal_type)
    {
    case 1:
        // std::cout << "  → Non-IDR slice\n";
        break;
    case 5:
        // std::cout << "  → IDR slice (keyframe)\n";
        break;
    case 6:
        // std::cout << "  → SEI\n";
        break;
    case 7:
        // std::cout << "  → SPS (sequence parameter set)\n";
        break;
    case 8:
        // std::cout << "  → PPS (picture parameter set)\n";
        break;
    default:
        // std::cout << "  → Unknown or unsupported\n";
        break;
    }
}

// Helper to check FFmpeg return codes
void check(int ret, const char *msg)
{
    if (ret < 0)
    {
        char errbuf[128];
        av_strerror(ret, errbuf, sizeof(errbuf));
        std::cerr << msg << ": " << errbuf << std::endl;
        exit(1);
    }
}

int main()
{
    const char *redis_url = std::getenv("REDIS_URL");
    // std::cout << "Using Redis URL: " << (redis_url ? redis_url : "redis://localhost:6379") << std::endl;
    Redis redis(redis_url ? redis_url : "redis://localhost:6379");

    std::string stream_name = "bigbuckbunny";
    std::string stream_key = "onionstream:stream:" + stream_name;

    // std::cout << "Registering stream" << std::endl;
    redis.sadd("onionstream:streams", stream_name);
    // std::cout << "Stream registered" << std::endl;

    const std::string filepath = "/demo/bigbuckbunny.avi";

    while (true)
    {
        AVFormatContext *fmt_ctx = nullptr;
        if (avformat_open_input(&fmt_ctx, filepath.c_str(), nullptr, nullptr) < 0)
        {
            std::cerr << "Failed to open file: " << filepath << std::endl;
            std::this_thread::sleep_for(std::chrono::seconds(1));
            continue;
        }

        if (avformat_find_stream_info(fmt_ctx, nullptr) < 0)
        {
            std::cerr << "Failed to retrieve stream info" << std::endl;
            avformat_close_input(&fmt_ctx);
            continue;
        }

        int video_stream_index = -1;
        for (unsigned i = 0; i < fmt_ctx->nb_streams; ++i)
        {
            if (fmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO)
            {
                video_stream_index = i;
                break;
            }
        }

        if (video_stream_index == -1)
        {
            std::cerr << "No video stream found" << std::endl;
            avformat_close_input(&fmt_ctx);
            continue;
        }

        AVCodecParameters *codecpar = fmt_ctx->streams[video_stream_index]->codecpar;

        // Set up decoder
        const AVCodec *decoder = avcodec_find_decoder(codecpar->codec_id);
        AVCodecContext *decoder_ctx = avcodec_alloc_context3(decoder);
        avcodec_parameters_to_context(decoder_ctx, codecpar);
        check(avcodec_open2(decoder_ctx, decoder, nullptr), "Cannot open decoder");

        // Set up encoder (H.264 with no B-frames)
        const AVCodec *encoder = avcodec_find_encoder(AV_CODEC_ID_H264);
        if (!encoder)
        {
            std::cerr << "H.264 encoder not found" << std::endl;
            avcodec_free_context(&decoder_ctx);
            avformat_close_input(&fmt_ctx);
            continue;
        }

        AVCodecContext *encoder_ctx = avcodec_alloc_context3(encoder);

        // Ensure width is even for H.264 compatibility
        int target_width = decoder_ctx->width;
        int target_height = decoder_ctx->height;
        if (target_width % 2 != 0)
        {
            target_width = (target_width + 1) & ~1; // Round up to nearest even number
        }
        if (target_height % 2 != 0)
        {
            target_height = (target_height + 1) & ~1; // Round up to nearest even number
        }

        encoder_ctx->width = target_width;
        encoder_ctx->height = target_height;
        encoder_ctx->time_base = fmt_ctx->streams[video_stream_index]->time_base;
        encoder_ctx->framerate = fmt_ctx->streams[video_stream_index]->avg_frame_rate;
        encoder_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
        encoder_ctx->bit_rate = 2000000;                 // 2 Mbps
        encoder_ctx->gop_size = 30;                      // GOP size
        encoder_ctx->max_b_frames = 0;                   // No B-frames!
        encoder_ctx->profile = FF_PROFILE_H264_BASELINE; // Baseline profile doesn't support B-frames

        // Additional encoder options for low latency and Annex B output
        AVDictionary *encoder_opts = nullptr;
        av_dict_set(&encoder_opts, "preset", "ultrafast", 0);
        av_dict_set(&encoder_opts, "tune", "zerolatency", 0);
        av_dict_set(&encoder_opts, "profile", "baseline", 0);
        av_dict_set(&encoder_opts, "annexb", "1", 0); // Force Annex B output

        check(avcodec_open2(encoder_ctx, encoder, &encoder_opts), "Cannot open encoder");
        av_dict_free(&encoder_opts);

        AVPacket *pkt = av_packet_alloc();
        AVFrame *frame = av_frame_alloc();
        AVFrame *resampled_frame = av_frame_alloc();

        // Set up frame properties for encoder
        resampled_frame->width = encoder_ctx->width;
        resampled_frame->height = encoder_ctx->height;
        resampled_frame->format = encoder_ctx->pix_fmt;
        av_frame_get_buffer(resampled_frame, 0);

        // Set up scaling context for format conversion and rescaling
        SwsContext *sws_ctx = sws_getContext(
            decoder_ctx->width, decoder_ctx->height, decoder_ctx->pix_fmt,
            encoder_ctx->width, encoder_ctx->height, encoder_ctx->pix_fmt,
            SWS_BILINEAR, nullptr, nullptr, nullptr);

        if (!sws_ctx)
        {
            std::cerr << "Failed to create scaling context" << std::endl;
            av_frame_free(&frame);
            av_frame_free(&resampled_frame);
            av_packet_free(&pkt);
            avcodec_free_context(&decoder_ctx);
            avcodec_free_context(&encoder_ctx);
            avformat_close_input(&fmt_ctx);
            continue;
        }

        while (av_read_frame(fmt_ctx, pkt) >= 0)
        {
            if (pkt->stream_index == video_stream_index)
            {
                // Decode the packet
                int ret = avcodec_send_packet(decoder_ctx, pkt);
                if (ret < 0)
                {
                    std::cerr << "Error sending packet to decoder" << std::endl;
                    av_packet_unref(pkt);
                    continue;
                }

                while (ret >= 0)
                {
                    ret = avcodec_receive_frame(decoder_ctx, frame);
                    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                        break;
                    else if (ret < 0)
                    {
                        std::cerr << "Error receiving frame from decoder" << std::endl;
                        break;
                    }

                    // Scale/convert frame data using sws_scale
                    int ret_scale = sws_scale(
                        sws_ctx,
                        frame->data, frame->linesize,
                        0, decoder_ctx->height,
                        resampled_frame->data, resampled_frame->linesize);

                    if (ret_scale < 0)
                    {
                        std::cerr << "Error scaling frame" << std::endl;
                        break;
                    }

                    // Copy timing properties
                    av_frame_copy_props(resampled_frame, frame);

                    // Re-encode the frame
                    ret = avcodec_send_frame(encoder_ctx, resampled_frame);
                    if (ret < 0)
                    {
                        std::cerr << "Error sending frame to encoder" << std::endl;
                        break;
                    }

                    AVPacket *encoded_pkt = av_packet_alloc();

                    while (ret >= 0)
                    {
                        ret = avcodec_receive_packet(encoder_ctx, encoded_pkt);
                        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                            break;
                        else if (ret < 0)
                        {
                            std::cerr << "Error receiving packet from encoder" << std::endl;
                            break;
                        }

                        // The encoder should now output in Annex B format directly
                        parse_nal(encoded_pkt->data, encoded_pkt->size);
                        std::string nal(reinterpret_cast<char *>(encoded_pkt->data), encoded_pkt->size);

                        // Determine frame type for logging
                        std::string frame_type = (encoded_pkt->flags & AV_PKT_FLAG_KEY) ? "keyframe" : "frame";

                        // Publish to Redis Pub/Sub channel
                        redis.publish(stream_key, nal);
                        // std::cout << "Published " << frame_type << " of size " << encoded_pkt->size << " to channel: " << stream_key << std::endl;
                        av_packet_free(&encoded_pkt);
                        encoded_pkt = av_packet_alloc();
                    }
                    av_packet_free(&encoded_pkt);
                }

                std::this_thread::sleep_for(std::chrono::milliseconds(33)); // simulate ~30 fps
            }
            av_packet_unref(pkt);
        }

        av_frame_free(&frame);
        av_frame_free(&resampled_frame);
        av_packet_free(&pkt);
        sws_freeContext(sws_ctx);
        avcodec_free_context(&decoder_ctx);
        avcodec_free_context(&encoder_ctx);
        avformat_close_input(&fmt_ctx);

        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    return 0;
}
