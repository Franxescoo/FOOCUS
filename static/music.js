(() => {
  const form=document.getElementById("music-search-form");
  const input=document.getElementById("music-query");
  const status=document.getElementById("music-status");
  const results=document.getElementById("music-results");
  const playerWrap=document.getElementById("music-player-wrap");
  const youtubeLink=document.getElementById("youtube-search-link");
  const openYoutube=document.getElementById("open-youtube");
  let player=null, pendingVideoId=null, loadingApi=false;

  function setLinks(query) {
    const url="https://music.youtube.com/search?q="+encodeURIComponent(query||"lofi music for studying");
    youtubeLink.href=url; openYoutube.href=url;
  }
  function createPlayer() {
    if(player || !window.YT || !window.YT.Player) return;
    player=new YT.Player("youtube-player",{
      width:"100%",height:"100%",videoId:pendingVideoId||"",
      playerVars:{playsinline:1,rel:0},
      events:{
        onReady:()=>{if(pendingVideoId) player.loadVideoById(pendingVideoId);},
        onError:()=>{status.textContent="Este video no permite reproducirse aquí. Prueba otro o ábrelo en YouTube Music.";}
      }
    });
  }
  function loadPlayerApi() {
    if(window.YT&&window.YT.Player){createPlayer();return;}
    if(loadingApi)return;
    loadingApi=true;
    const previous=window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady=()=>{if(typeof previous==="function")previous();createPlayer();};
    const script=document.createElement("script");
    script.src="https://www.youtube.com/iframe_api";script.async=true;document.head.appendChild(script);
  }
  function play(id,title) {
    pendingVideoId=id;playerWrap.hidden=false;loadPlayerApi();
    if(player&&player.loadVideoById)player.loadVideoById(id);
    status.textContent="Intentando reproducir: "+title;
    playerWrap.scrollIntoView({behavior:"smooth",block:"nearest"});
  }
  function render(items) {
    results.replaceChildren();
    items.forEach(item=>{
      const button=document.createElement("button");
      button.type="button";button.className="music-result";button.setAttribute("aria-pressed","false");
      const img=document.createElement("img");img.alt="";img.loading="lazy";
      if(item.thumbnail)img.src=item.thumbnail;
      const copy=document.createElement("span");copy.className="music-result-copy";
      const title=document.createElement("span");title.className="music-result-title";title.textContent=item.title;
      const channel=document.createElement("span");channel.className="music-result-channel";channel.textContent=item.channel;
      copy.append(title,channel);button.append(img,copy);
      button.addEventListener("click",()=>{
        results.querySelectorAll(".music-result").forEach(el=>el.setAttribute("aria-pressed","false"));
        button.setAttribute("aria-pressed","true");play(item.id,item.title);
      });
      results.append(button);
    });
  }
  async function search(query) {
    const q=query.trim();
    if(!q){status.textContent="Escribe una canción, artista o estilo musical.";input.focus();return;}
    setLinks(q);results.replaceChildren();status.textContent="Buscando en YouTube…";
    const submit=form.querySelector("button[type=submit]");submit.disabled=true;
    try {
      const response=await fetch("/api/music/search?q="+encodeURIComponent(q));
      const data=await response.json();
      if(data.items&&data.items.length){render(data.items);status.textContent="Elige un resultado para intentar reproducirlo.";}
      else status.textContent=data.message||"No se encontraron resultados.";
    } catch(e) {
      status.textContent="No se pudo conectar con la búsqueda. Puedes abrir YouTube Music directamente.";
    } finally {submit.disabled=false;}
  }
  form.addEventListener("submit",e=>{e.preventDefault();search(input.value);});
  document.querySelectorAll("[data-query]").forEach(button=>button.addEventListener("click",()=>{
    input.value=button.dataset.query;search(button.dataset.query);
  }));
  setLinks("");
})();