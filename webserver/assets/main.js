function updateHLS(element){
    player.src = extractPlaylistURL(element);
}
const player = document.getElementById("player");
HookHLSHandler(player);

document.getElementById('HLS-submit').addEventListener('click', function() {
    updateHLS(this.parentElement);
});
