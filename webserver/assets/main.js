const base_url = "/api/playlist.m3u8";

document.addEventListener('DOMContentLoaded', function () {
  // Check if HLS is supported in this browser
  const video = document.getElementById('player');
    
  document.getElementById('HLS-submit').addEventListener('click', function (event) {
    event.preventDefault();
    const form = document.getElementById('hls-form');
    let url = base_url + "?"
    for (let i = 0; i < form.elements.length; i++) {
      const element = form.elements[i];
      if (element.name && element.value) {
        url += `&${element.name}=${encodeURIComponent(element.value)}`;
      }
    }

    if (Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(url);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, function () {
            video.play();
        });
    }
    else {
        // Tries to load it using src, with luck the browser will be compatible
        video.src = url;
        video.play();
    }
  });
});
