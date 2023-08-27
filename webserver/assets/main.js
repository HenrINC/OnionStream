const base_url = "/api/playlist.m3u8";


document.addEventListener('DOMContentLoaded', function () {
    // Check if HLS is supported in this browser
    if (Hls.isSupported()) {
        const hls = new Hls();
        const video = document.getElementById('player');

        document.getElementById('HLS-submit').addEventListener('click', function (event) {
            event.preventDefault();

            const form = document.getElementById('hls-form');

            // Start building the URL for the request
            let url = base_url + "?"

            // Dynamically append other parameters
            for (let i = 0; i < form.elements.length; i++) {
                const element = form.elements[i];

                if (element.name && element.value) {
                    url += `&${element.name}=${encodeURIComponent(element.value)}`;
                }
            }

            // Load the stream using hls.js
            if (hls) {
                hls.loadSource(url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function () {
                    video.play();
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                // If HLS isn't supported natively but the video tag can play it
                video.src = url;
                video.addEventListener('loadedmetadata', function () {
                    video.play();
                });
            }
        });
    } else {
        alert('HLS is not supported in this browser!');
    }
});
