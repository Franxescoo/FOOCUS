(() => {
  const form = document.getElementById("music-search-form");
  const input = document.getElementById("music-query");
  const status = document.getElementById("music-status");
  const results = document.getElementById("music-results");
  const playerWrap = document.getElementById("music-player-wrap");
  const youtubeLink = document.getElementById("youtube-search-link");
  const openYoutube = document.getElementById("open-youtube");
  const library = document.getElementById("music-library");
  const libraryCount = document.getElementById("library-count");
  const SAVED_KEY = "focusflow_saved_music_v1";
  let saved = loadSaved();
  let player = null;
  let pendingVideo = null;
  let apiLoading = false;
  let isPlaying = false;
  const playPauseButton = document.getElementById("music-play-pause");
  const volumeDownButton = document.getElementById("music-volume-down");
  const volumeUpButton = document.getElementById("music-volume-up");
  const volumeSlider = document.getElementById("music-volume");
  const volumeValue = document.getElementById("music-volume-value");

  function updatePlayPause(playing) {
    isPlaying = playing;
    playPauseButton.innerHTML = playing ? "Ⅱ <span>Pausar</span>" : "▶ <span>Reanudar</span>";
    playPauseButton.setAttribute("aria-label", playing ? "Pausar música" : "Reanudar música");
    playPauseButton.title = playing ? "Pausar música" : "Reanudar música";
  }

  function setVolume(value) {
    const volume = Math.max(0, Math.min(100, Number(value)));
    volumeSlider.value = String(volume);
    volumeValue.value = volume + "%";
    volumeValue.textContent = volume + "%";
    if (player && typeof player.setVolume === "function") player.setVolume(volume);
    if (player && volume === 0 && typeof player.mute === "function") player.mute();
    else if (player && typeof player.unMute === "function") player.unMute();
  }

  playPauseButton.addEventListener("click", () => {
    if (!player || typeof player.getPlayerState !== "function") {
      status.textContent = "Primero selecciona una canción para reproducirla.";
      return;
    }
    const state = player.getPlayerState();
    if (state === YT.PlayerState.PLAYING) player.pauseVideo();
    else player.playVideo();
  });
  volumeDownButton.addEventListener("click", () => setVolume(Number(volumeSlider.value) - 10));
  volumeUpButton.addEventListener("click", () => setVolume(Number(volumeSlider.value) + 10));
  volumeSlider.addEventListener("input", () => setVolume(volumeSlider.value));

  function loadSaved() {
    try { return JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"); }
    catch (error) { return []; }
  }

  function saveLibrary() {
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(saved)); }
    catch (error) { status.textContent = "No se pudo guardar la colección en este navegador."; }
    renderLibrary();
  }

  function renderLibrary() {
    library.replaceChildren();
    libraryCount.textContent = saved.length + (saved.length === 1 ? " guardada" : " guardadas");
    if (!saved.length) {
      const empty = document.createElement("p");
      empty.className = "library-empty";
      empty.textContent = "Guarda canciones con ☆ y aparecerán aquí.";
      library.append(empty);
      return;
    }
    saved.forEach(item => {
      const row = document.createElement("div");
      row.className = "saved-track";
      const playButton = document.createElement("button");
      playButton.type = "button";
      playButton.className = "saved-track-play";
      playButton.textContent = "▶";
      playButton.setAttribute("aria-label", "Reproducir " + item.title);
      playButton.addEventListener("click", () => play(item));
      const info = document.createElement("span");
      info.className = "saved-track-info";
      const title = document.createElement("strong");
      title.textContent = item.title;
      const artist = document.createElement("small");
      artist.textContent = item.channel || "YouTube Music";
      info.append(title, artist);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "saved-track-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "Quitar " + item.title + " de Mi música");
      remove.addEventListener("click", () => {
        saved = saved.filter(track => track.id !== item.id);
        saveLibrary();
      });
      row.append(playButton, info, remove);
      library.append(row);
    });
  }

  function setLinks(query) {
    const url = "https://music.youtube.com/search?q=" + encodeURIComponent(query || "lofi music for studying");
    youtubeLink.href = url;
    openYoutube.href = url;
  }

  function setFallbackLink(link, video) {
    link.href = "https://music.youtube.com/watch?v=" + encodeURIComponent(video.id);
    link.textContent = "Abrir canción en YouTube Music ↗";
  }

  function playerContainer() {
    let node = document.getElementById("youtube-player");
    if (!node || node.tagName.toLowerCase() !== "div") {
      const replacement = document.createElement("div");
      replacement.id = "youtube-player";
      if (node && node.parentNode) node.parentNode.replaceChild(replacement, node);
      else playerWrap.insertBefore(replacement, playerWrap.querySelector(".player-note"));
      node = replacement;
    }
    return node;
  }

  function showFallback(video, reason) {
    playerWrap.hidden = false;
    const node = playerContainer();
    node.replaceChildren();
    const box = document.createElement("div");
    box.className = "playback-fallback";
    const title = document.createElement("strong");
    title.textContent = "No se pudo reproducir dentro de FocusFlow";
    const note = document.createElement("p");
    note.textContent = reason || "Este video puede tener restricciones de reproducción incrustada.";
    const link = document.createElement("a");
    link.href = "https://music.youtube.com/watch?v=" + encodeURIComponent(video.id);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Abrir canción en YouTube Music ↗";
    box.append(title, note, link);
    node.append(box);
    status.textContent = "La canción se encontró, pero YouTube no permitió reproducirla aquí.";
  }

  function createPlayer() {
    if (player || !window.YT || !window.YT.Player || !pendingVideo) return;
    const node = playerContainer();
    player = new YT.Player(node, {
      width: "100%",
      height: "100%",
      videoId: pendingVideo.id,
      playerVars: { playsinline: 1, rel: 0, origin: window.location.origin },
      events: {
        onReady: event => {
          event.target.setVolume(Number(volumeSlider.value));
          if (pendingVideo) event.target.loadVideoById(pendingVideo.id);
        },
        onStateChange: event => {
          if (event.data === YT.PlayerState.PLAYING) updatePlayPause(true);
          else if (event.data === YT.PlayerState.PAUSED || event.data === YT.PlayerState.ENDED) updatePlayPause(false);
        },
        onError: event => {
          const video = pendingVideo;
          const code = event.data;
          let reason = "YouTube rechazó la reproducción (error " + code + ").";
          if (code === 5) reason = "El reproductor HTML5 de YouTube no pudo reproducir este video. Puede ser una incompatibilidad del navegador o del formato del video; prueba otra canción o ábrela en YouTube.";
          if (code === 100) reason = "El video fue eliminado o es privado.";
          if (code === 101 || code === 150) reason = "El propietario no permite reproducir este video en otras páginas.";
          if (code === 153) reason = "YouTube no recibió información suficiente para identificar el reproductor. Revisa que abras FocusFlow desde http://127.0.0.1:5000 y no desde un archivo HTML local; si continúa, abre la canción en YouTube Music.";
          if (video) showFallback(video, reason);
        }
      }
    });
  }

  function loadPlayerApi() {
    if (window.YT && window.YT.Player) {
      createPlayer();
      return;
    }
    if (apiLoading) return;
    apiLoading = true;
    window.onYouTubeIframeAPIReady = createPlayer;
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => {
      apiLoading = false;
      if (pendingVideo) showFallback(pendingVideo, "No se pudo cargar el reproductor de YouTube. Comprueba tu conexión.");
    };
    document.head.appendChild(script);
  }

  function play(video) {
    pendingVideo = video;
    playerWrap.hidden = false;
    if (player && typeof player.destroy === "function") {
      player.destroy();
      player = null;
    }
    const node = playerContainer();
    node.replaceChildren();
    updatePlayPause(false);
    status.textContent = "Intentando reproducir: " + video.title;
    loadPlayerApi();
    playerWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function render(items) {
    results.replaceChildren();
    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "music-result-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "music-result";
      button.setAttribute("aria-pressed", "false");
      const img = document.createElement("img");
      img.alt = "";
      img.loading = "lazy";
      if (item.thumbnail) img.src = item.thumbnail;
      const copy = document.createElement("span");
      copy.className = "music-result-copy";
      const title = document.createElement("span");
      title.className = "music-result-title";
      title.textContent = item.title;
      const channel = document.createElement("span");
      channel.className = "music-result-channel";
      channel.textContent = item.channel;
      copy.append(title, channel);
      button.append(img, copy);
      button.addEventListener("click", () => {
        results.querySelectorAll(".music-result").forEach(el => el.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
        play(item);
      });
      const favorite = document.createElement("button");
      favorite.type = "button";
      favorite.className = "music-save";
      const isSaved = () => saved.some(track => track.id === item.id);
      favorite.textContent = isSaved() ? "★" : "☆";
      favorite.setAttribute("aria-label", isSaved() ? "Quitar de Mi música" : "Guardar en Mi música");
      favorite.title = favorite.getAttribute("aria-label");
      favorite.addEventListener("click", () => {
        if (isSaved()) {
          saved = saved.filter(track => track.id !== item.id);
          status.textContent = "Canción quitada de Mi música.";
        } else {
          saved.unshift(item);
          status.textContent = "Canción guardada en Mi música.";
        }
        saveLibrary();
        favorite.textContent = isSaved() ? "★" : "☆";
        favorite.setAttribute("aria-label", isSaved() ? "Quitar de Mi música" : "Guardar en Mi música");
        favorite.title = favorite.getAttribute("aria-label");
      });
      row.append(button, favorite);
      results.append(row);
    });
  }

  async function search(query) {
    const q = query.trim();
    if (!q) {
      status.textContent = "Escribe una canción, artista o estilo musical.";
      input.focus();
      return;
    }
    setLinks(q);
    results.replaceChildren();
    status.textContent = "Buscando en YouTube Music...";
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const response = await fetch("/api/music/search?q=" + encodeURIComponent(q), { cache: "no-store" });
      const data = await response.json();
      if (data.items && data.items.length) {
        render(data.items);
        status.textContent = "Elige una canción para reproducirla.";
      } else {
        status.textContent = data.message || "No se encontraron resultados.";
      }
    } catch (error) {
      status.textContent = "No se pudo conectar con la búsqueda. Puedes abrir YouTube Music directamente.";
    } finally {
      submit.disabled = false;
    }
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    search(input.value);
  });
  document.querySelectorAll("[data-query]").forEach(button => button.addEventListener("click", () => {
    input.value = button.dataset.query;
    search(button.dataset.query);
  }));
  setLinks("");
  renderLibrary();
})();