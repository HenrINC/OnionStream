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
#include <libavutil/opt.h>
#include <libavutil/channel_layout.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
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
    std::string stream_prefix = "onionstream:stream:" + stream_name + ":";

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
        int audio_stream_index = -1;
        for (unsigned i = 0; i < fmt_ctx->nb_streams; ++i)
        {
            if (fmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO)
            {
                video_stream_index = i;
            }
            else if (fmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_AUDIO)
            {
                audio_stream_index = i;
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
        // Remove fixed bitrate - using CRF for variable bitrate with consistent quality
        // encoder_ctx->bit_rate = 750000;              // Removed: using CRF instead
        encoder_ctx->gop_size = 30;                      // GOP size
        encoder_ctx->max_b_frames = 0;                   // No B-frames!
        encoder_ctx->profile = AV_PROFILE_H264_BASELINE; // Baseline profile doesn't support B-frames

        // Optimized encoder options: CRF for quality-based encoding
        AVDictionary *encoder_opts = nullptr;
        av_dict_set(&encoder_opts, "preset", "fast", 0);      // Much better compression, still under 100ms
        av_dict_set(&encoder_opts, "tune", "zerolatency", 0); // Keep low latency
        av_dict_set(&encoder_opts, "profile", "baseline", 0); // Ancient client compatibility
        av_dict_set(&encoder_opts, "level", "3.0", 0);        // Safe level for old hardware
        av_dict_set(&encoder_opts, "crf", "28", 0);           // Quality target (18-28 range, 28=good for streaming)
        av_dict_set(&encoder_opts, "maxrate", "1200k", 0);    // Soft cap to prevent bandwidth spikes
        av_dict_set(&encoder_opts, "bufsize", "2400k", 0);    // Buffer size (2x maxrate)
        av_dict_set(&encoder_opts, "annexb", "1", 0);         // Force Annex B output
        av_dict_set(&encoder_opts, "refs", "1", 0);           // Single reference frame (easier decode)
        av_dict_set(&encoder_opts, "me_method", "hex", 0);    // Good motion estimation without being too slow
        av_dict_set(&encoder_opts, "subq", "6", 0);           // Good subpixel motion estimation
        av_dict_set(&encoder_opts, "trellis", "1", 0);        // Enable trellis quantization (better compression)
        // av_dict_set(&encoder_opts, "slice-min-size", "65536", 0);  // 64KB min slice size
        // av_dict_set(&encoder_opts, "slice-max-size", "524288", 0); // 512KB max slice size

        check(avcodec_open2(encoder_ctx, encoder, &encoder_opts), "Cannot open encoder");
        av_dict_free(&encoder_opts);

        // Audio decoder and encoder setup
        AVCodecContext *audio_decoder_ctx = nullptr;
        AVCodecContext *audio_encoder_ctx = nullptr;
        SwrContext *swr_ctx = nullptr;

        if (audio_stream_index != -1)
        {
            AVCodecParameters *audio_codecpar = fmt_ctx->streams[audio_stream_index]->codecpar;

            // Set up audio decoder
            const AVCodec *audio_decoder = avcodec_find_decoder(audio_codecpar->codec_id);
            if (audio_decoder)
            {
                audio_decoder_ctx = avcodec_alloc_context3(audio_decoder);
                avcodec_parameters_to_context(audio_decoder_ctx, audio_codecpar);
                check(avcodec_open2(audio_decoder_ctx, audio_decoder, nullptr), "Cannot open audio decoder");

                // Set up Opus encoder
                const AVCodec *opus_encoder = avcodec_find_encoder(AV_CODEC_ID_OPUS);
                if (opus_encoder)
                {
                    audio_encoder_ctx = avcodec_alloc_context3(opus_encoder);
                    audio_encoder_ctx->sample_rate = 48000;                      // Opus standard sample rate
                    av_channel_layout_default(&audio_encoder_ctx->ch_layout, 2); // Stereo
                    audio_encoder_ctx->sample_fmt = AV_SAMPLE_FMT_S16;           // Opus encoder expects S16
                    audio_encoder_ctx->bit_rate = 128000;                        // 128 kbps
                    audio_encoder_ctx->time_base = {1, audio_encoder_ctx->sample_rate};

                    check(avcodec_open2(audio_encoder_ctx, opus_encoder, nullptr), "Cannot open Opus encoder");

                    // Set up resampling context
                    swr_ctx = swr_alloc();
                    av_opt_set_chlayout(swr_ctx, "in_chlayout", &audio_decoder_ctx->ch_layout, 0);
                    av_opt_set_chlayout(swr_ctx, "out_chlayout", &audio_encoder_ctx->ch_layout, 0);
                    av_opt_set_int(swr_ctx, "in_sample_rate", audio_decoder_ctx->sample_rate, 0);
                    av_opt_set_int(swr_ctx, "out_sample_rate", audio_encoder_ctx->sample_rate, 0);
                    av_opt_set_sample_fmt(swr_ctx, "in_sample_fmt", audio_decoder_ctx->sample_fmt, 0);
                    av_opt_set_sample_fmt(swr_ctx, "out_sample_fmt", audio_encoder_ctx->sample_fmt, 0);
                    swr_init(swr_ctx);
                }
            }
        }

        AVPacket *pkt = av_packet_alloc();
        AVFrame *frame = av_frame_alloc();
        AVFrame *resampled_frame = av_frame_alloc();
        AVFrame *audio_frame = av_frame_alloc();
        AVFrame *resampled_audio_frame = av_frame_alloc();

        // Set up frame properties for encoder
        resampled_frame->width = encoder_ctx->width;
        resampled_frame->height = encoder_ctx->height;
        resampled_frame->format = encoder_ctx->pix_fmt;
        av_frame_get_buffer(resampled_frame, 0);

        // Set up audio frame properties for Opus encoder
        if (audio_encoder_ctx)
        {
            resampled_audio_frame->sample_rate = audio_encoder_ctx->sample_rate;
            av_channel_layout_copy(&resampled_audio_frame->ch_layout, &audio_encoder_ctx->ch_layout);
            resampled_audio_frame->format = audio_encoder_ctx->sample_fmt;
            resampled_audio_frame->nb_samples = audio_encoder_ctx->frame_size;
            av_frame_get_buffer(resampled_audio_frame, 0);
        }

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

        bool processing_error = false;
        auto start_time = std::chrono::high_resolution_clock::now();
        int64_t frame_count = 0;
        auto last_stats = start_time;

        while (av_read_frame(fmt_ctx, pkt) >= 0 && !processing_error)
        {
            if (pkt->stream_index == video_stream_index)
            {
                // Video processing (existing code)
                int ret = avcodec_send_packet(decoder_ctx, pkt);
                if (ret < 0)
                {
                    std::cerr << "Error sending video packet to decoder" << std::endl;
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
                        processing_error = true;
                        break;
                    }

                    // Copy timing properties
                    av_frame_copy_props(resampled_frame, frame);

                    // Re-encode the frame
                    ret = avcodec_send_frame(encoder_ctx, resampled_frame);
                    if (ret < 0)
                    {
                        std::cerr << "Error sending frame to encoder" << std::endl;
                        processing_error = true;
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
                            processing_error = true;
                            break;
                        }

                        // The encoder should now output in Annex B format directly
                        // parse_nal(encoded_pkt->data, encoded_pkt->size);
                        std::string nal(reinterpret_cast<char *>(encoded_pkt->data), encoded_pkt->size);

                        // Determine frame type for logging
                        std::string frame_type = (encoded_pkt->flags & AV_PKT_FLAG_KEY) ? "keyframe" : "frame";

                        // Publish to Redis Pub/Sub channel
                        redis.publish((stream_prefix + "video"), nal);
                        // std::cout << "Published " << frame_type << " of size " << encoded_pkt->size << " to channel: " << stream_key << std::endl;

                        // Unref the packet to reset it for reuse
                        av_packet_unref(encoded_pkt);
                    }
                    av_packet_free(&encoded_pkt);

                    frame_count++;
                }

                // Proper frame timing based on actual video framerate
                auto current_time = std::chrono::high_resolution_clock::now();
                auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(current_time - start_time);

                // Calculate expected time for this frame number
                double fps = av_q2d(fmt_ctx->streams[video_stream_index]->avg_frame_rate);
                if (fps <= 0)
                    fps = 30.0; // fallback

                auto expected_time = std::chrono::milliseconds((int64_t)(frame_count * 1000.0 / fps));

                if (elapsed < expected_time)
                {
                    auto sleep_time = expected_time - elapsed;
                    std::this_thread::sleep_for(sleep_time);
                }

                // Print stats every 30 seconds
                if (std::chrono::duration_cast<std::chrono::seconds>(current_time - last_stats).count() >= 30)
                {
                    double actual_fps = frame_count * 1000.0 / elapsed.count();
                    std::cout << "Frames: " << frame_count << ", Target FPS: " << fps
                              << ", Actual FPS: " << actual_fps << std::endl;
                    last_stats = current_time;
                }
            }
            else if (pkt->stream_index == audio_stream_index && audio_decoder_ctx && audio_encoder_ctx)
            {
                // Audio processing
                int ret = avcodec_send_packet(audio_decoder_ctx, pkt);
                if (ret < 0)
                {
                    std::cerr << "Error sending audio packet to decoder" << std::endl;
                    av_packet_unref(pkt);
                    continue;
                }

                while (ret >= 0)
                {
                    ret = avcodec_receive_frame(audio_decoder_ctx, audio_frame);
                    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                        break;
                    else if (ret < 0)
                    {
                        std::cerr << "Error receiving audio frame from decoder" << std::endl;
                        break;
                    }

                    // Resample audio
                    if (swr_ctx)
                    {
                        int out_samples = swr_convert(swr_ctx,
                                                      resampled_audio_frame->data, resampled_audio_frame->nb_samples,
                                                      (const uint8_t **)audio_frame->data, audio_frame->nb_samples);

                        if (out_samples < 0)
                        {
                            std::cerr << "Error resampling audio" << std::endl;
                            break;
                        }

                        resampled_audio_frame->nb_samples = out_samples;
                        resampled_audio_frame->pts = audio_frame->pts;
                    }

                    // Encode audio to Opus
                    ret = avcodec_send_frame(audio_encoder_ctx, resampled_audio_frame);
                    if (ret < 0)
                    {
                        std::cerr << "Error sending audio frame to encoder" << std::endl;
                        break;
                    }

                    AVPacket *encoded_audio_pkt = av_packet_alloc();

                    while (ret >= 0)
                    {
                        ret = avcodec_receive_packet(audio_encoder_ctx, encoded_audio_pkt);
                        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                            break;
                        else if (ret < 0)
                        {
                            std::cerr << "Error receiving audio packet from encoder" << std::endl;
                            break;
                        }

                        // Publish Opus audio data to Redis
                        std::string opus_data(reinterpret_cast<char *>(encoded_audio_pkt->data), encoded_audio_pkt->size);
                        redis.publish((stream_prefix + "audio"), opus_data);

                        av_packet_free(&encoded_audio_pkt);
                        encoded_audio_pkt = av_packet_alloc();
                    }
                    av_packet_free(&encoded_audio_pkt);
                }
            }
            av_packet_unref(pkt);
        }
        av_frame_free(&frame);
        av_frame_free(&resampled_frame);
        av_frame_free(&audio_frame);
        av_frame_free(&resampled_audio_frame);
        av_packet_free(&pkt);
        sws_freeContext(sws_ctx);
        if (swr_ctx)
            swr_free(&swr_ctx);
        avcodec_free_context(&decoder_ctx);
        avcodec_free_context(&encoder_ctx);
        if (audio_decoder_ctx)
            avcodec_free_context(&audio_decoder_ctx);
        if (audio_encoder_ctx)
            avcodec_free_context(&audio_encoder_ctx);
        avformat_close_input(&fmt_ctx);

        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    return 0;
}
