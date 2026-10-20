(() => {
  const form = document.getElementById("music-search-form");
  const input = document.getElementById("music-query");
  const status = document.getElementById("music-status");
  const results = document.getElementById("music-results");
  const playerWrap = document.getElementById("music-player-wrap");
  const youtubeLink = document.getElementById("youtube-search-link");
  const openYoutube = document.getElementById("open-youtube");
  let player = null;
  let pendingVideo = null;
  let apiLoading = false;

  function setLinks(query) {
    const url = "https://music.youtube.com/search?q=" + encodeURIComponent(query || "lofi music for studying");
    youtubeLink.href = url;
    openYoutube.href = url;
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
    link.href = "https://www.youtube.com/watch?v=" + encodeURIComponent(video.id);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Reproducir en YouTube";
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
          if (pendingVideo) event.target.loadVideoById(pendingVideo.id);
        },
        onError: event => {
          const video = pendingVideo;
          const code = event.data;
          let reason = "YouTube rechazó la reproducción (error " + code + ").";
          if (code === 100) reason = "El video fue eliminado o es privado.";
          if (code === 101 || code === 150) reason = "El propietario no permite reproducir este video en otras páginas.";
          if (code === 153) reason = "YouTube no recibió la información de referencia necesaria del reproductor.";
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
    status.textContent = "Intentando reproducir: " + video.title;
    loadPlayerApi();
    playerWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function render(items) {
    results.replaceChildren();
    items.forEach(item => {
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
      results.append(button);
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
})();