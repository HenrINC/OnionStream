function extractPlaylistURL(form, base_url = "/api/playlist.m3u8"){
    let params = [];
    console.log(form);
    for(let input of form.querySelectorAll("input")) {
        console.log(input);
        if(input.value.trim() !== '') { // Check if the input has a value
            params.push(`${input.name}=${encodeURIComponent(input.value)}`);
        }
    }
    return base_url + "?" + params.join("&");
}

function HookHLSHandler(element, handler=loadHLS) {
    function handleMutation(mutationsList, observer) {
        for(let mutation of mutationsList) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'src') {
                handler(element);
            }
        }
    }
    const observerConfig = { attributes: true, childList: false, subtree: false };
    const observer = new MutationObserver(handleMutation);
    observer.observe(element, observerConfig);
    return observer;
}

function loadHLS(element) {
    if (Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(element.src);
        hls.attachMedia(element);
        hls.on(Hls.Events.MANIFEST_PARSED, function() {
            element.play();
        });
    } else if (element.canPlayType('application/vnd.apple.mpegurl')) {
        element.addEventListener('loadedmetadata', function() {
            element.play();
        });
    } else {
        console.error('This browser does not support HLS playback');
    }
}