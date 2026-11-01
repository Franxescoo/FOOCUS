(() => {
  "use strict";
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const workspaceForm = document.getElementById("canvas-workspace-form");
  const boardForm = document.getElementById("canvas-board-form");
  const workspaceSelect = document.getElementById("canvas-board-workspace");
  const workspaceList = document.getElementById("canvas-workspaces-list");
  const boardList = document.getElementById("canvas-boards-list");
  const status = document.getElementById("canvas-status");
  const workspaceCount = document.getElementById("canvas-workspace-count");
  const boardCount = document.getElementById("canvas-board-count");
  const boardsTitle = document.getElementById("canvas-boards-list-title");
  const showAllBoardsButton = document.getElementById("canvas-show-all-boards");
  if (!workspaceForm || !boardForm) return;
  let cachedWorkspaces = [];
  let cachedBoards = [];
  let activeWorkspaceFilter = null;

  async function api(url, options = {}) {
    const method = options.method || "GET";
    const response = await fetch(url, {
      cache: "no-store", ...options,
      headers: {
        "Accept": "application/json",
        ...(options.body ? {"Content-Type": "application/json"} : {}),
        ...(method !== "GET" ? {"X-CSRF-Token": csrfToken} : {}),
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.message || "No se pudo completar la operación.");
    return data;
  }

  function setStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  }

  function makeButton(label, className, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function renderWorkspaceOptions(workspaces) {
    const selected = workspaceSelect.value;
    workspaceSelect.replaceChildren(new Option("Independiente", ""));
    for (const workspace of workspaces) workspaceSelect.add(new Option(workspace.name, String(workspace.id)));
    if ([...workspaceSelect.options].some(option => option.value === selected)) workspaceSelect.value = selected;
  }

  function renderWorkspaces(workspaces) {
    workspaceList.replaceChildren();
    workspaceCount.textContent = String(workspaces.length);
    if (!workspaces.length) {
      const empty = document.createElement("p");
      empty.className = "canvas-empty";
      empty.textContent = "Todavía no tienes espacios. Puedes crear uno para agrupar tus tableros.";
      workspaceList.append(empty);
      return;
    }
    for (const workspace of workspaces) {
      const card = document.createElement("article");
      card.className = "canvas-item-card";
      card.dataset.color = workspace.color;
      const heading = document.createElement("div");
      heading.className = "canvas-item-heading";
      const name = document.createElement("h4");
      name.textContent = workspace.name;
      const count = document.createElement("span");
      count.className = "canvas-item-count";
      count.textContent = String(workspace.board_count) + " tableros";
      heading.append(name, count);
      const description = document.createElement("p");
      description.className = "canvas-item-description";
      description.textContent = workspace.description || "Sin descripción";
      const actions = document.createElement("div");
      actions.className = "canvas-item-actions";
      actions.append(
        makeButton("Ver tableros", "focus-reset", () => {
          activeWorkspaceFilter = workspace.id;
          boardsTitle.textContent = "Tableros · " + workspace.name;
          showAllBoardsButton.hidden = false;
          const associated = cachedBoards.filter(board => Number(board.workspace_id) === Number(workspace.id));
          renderBoards(associated, cachedWorkspaces);
        }),
        makeButton("Renombrar", "focus-reset", async () => {
          const nextName = window.prompt("Nuevo nombre del espacio:", workspace.name);
          if (nextName === null || !nextName.trim()) return;
          try {
            await api("/api/workspaces/" + workspace.id, {method:"PATCH", body:JSON.stringify({name:nextName})});
            setStatus("Espacio actualizado.");
            await refresh();
          } catch (error) { setStatus(error.message, true); }
        }),
        makeButton("Eliminar espacio", "canvas-danger-button", async () => {
          const message = workspace.board_count
            ? "Se eliminará «" + workspace.name + "», pero sus " + workspace.board_count + " tableros se conservarán como independientes. ¿Continuar?"
            : "¿Eliminar el espacio «" + workspace.name + "»?";
          if (!window.confirm(message)) return;
          try {
            await api("/api/workspaces/" + workspace.id, {
              method:"DELETE", body:JSON.stringify({preserve_boards:true})
            });
            setStatus("Espacio eliminado. Sus tableros se conservaron.");
            await refresh();
          } catch (error) { setStatus(error.message, true); }
        })
      );
      card.append(heading, description, actions);
      workspaceList.append(card);
    }
  }

  function renderBoards(boards, workspaces) {
    boardList.replaceChildren();
    boardCount.textContent = String(boards.length);
    if (!boards.length) {
      const empty = document.createElement("p");
      empty.className = "canvas-empty";
      empty.textContent = "Todavía no tienes tableros. Crea uno libre o estructurado para comenzar.";
      boardList.append(empty);
      return;
    }
    for (const board of boards) {
      const card = document.createElement("article");
      card.className = "canvas-item-card canvas-board-card";
      const heading = document.createElement("div");
      heading.className = "canvas-item-heading";
      const name = document.createElement("h4");
      name.textContent = board.title;
      const mode = document.createElement("span");
      mode.className = "canvas-item-count";
      mode.textContent = board.mode === "structured" ? "Estructurado" : "Libre";
      heading.append(name, mode);
      const location = document.createElement("p");
      location.className = "canvas-item-description";
      location.textContent = board.workspace_name ? "Espacio: " + board.workspace_name : "Tablero independiente";
      const actions = document.createElement("div");
      actions.className = "canvas-item-actions";
      actions.append(makeButton("Abrir tablero", "primary-button", async () => {
        if (typeof window.FOOCUSCanvasOpenEditor !== "function") {
          setStatus("No se pudo cargar el editor Canvas.", true);
          return;
        }
        await window.FOOCUSCanvasOpenEditor(board);
      }));
      actions.append(makeButton("Renombrar", "focus-reset", async () => {
        const nextTitle = window.prompt("Nuevo nombre del tablero:", board.title);
        if (nextTitle === null || !nextTitle.trim()) return;
        try {
          await api("/api/canvas/" + board.id, {method:"PATCH", body:JSON.stringify({title:nextTitle})});
          setStatus("Tablero actualizado.");
          await refresh();
        } catch (error) { setStatus(error.message, true); }
      }));
      const moveLabel = document.createElement("label");
      moveLabel.className = "canvas-move-label";
      moveLabel.textContent = "Ubicación";
      const moveSelect = document.createElement("select");
      moveSelect.setAttribute("aria-label", "Espacio para " + board.title);
      moveSelect.add(new Option("Independiente", ""));
      for (const workspace of workspaces) moveSelect.add(new Option(workspace.name, String(workspace.id)));
      moveSelect.value = board.workspace_id === null ? "" : String(board.workspace_id);
      moveLabel.append(moveSelect);
      actions.append(moveLabel, makeButton("Guardar ubicación", "focus-reset", async () => {
        const raw = moveSelect.value;
        try {
          await api("/api/canvas/" + board.id, {
            method:"PATCH", body:JSON.stringify({workspace_id:raw ? Number(raw) : null})
          });
          setStatus("Ubicación del tablero actualizada.");
          await refresh();
        } catch (error) { setStatus(error.message, true); }
      }));
      actions.append(makeButton("Eliminar", "canvas-danger-button", async () => {
        if (!window.confirm("¿Eliminar el tablero «" + board.title + "»? Esta acción no se puede deshacer.")) return;
        try {
          await api("/api/canvas/" + board.id, {method:"DELETE", body:JSON.stringify({confirm:true})});
          setStatus("Tablero eliminado.");
          await refresh();
        } catch (error) { setStatus(error.message, true); }
      }));
      card.append(heading, location, actions);
      boardList.append(card);
    }
  }

  async function refresh() {
    setStatus("Cargando espacios y tableros…");
    try {
      const results = await Promise.all([api("/api/workspaces"), api("/api/canvas")]);
      cachedWorkspaces = results[0].items;
      cachedBoards = results[1].items;
      renderWorkspaceOptions(cachedWorkspaces);
      renderWorkspaces(cachedWorkspaces);
      const activeWorkspace = cachedWorkspaces.find(item => item.id === activeWorkspaceFilter);
      if (activeWorkspace) {
        boardsTitle.textContent = "Tableros · " + activeWorkspace.name;
        showAllBoardsButton.hidden = false;
        renderBoards(cachedBoards.filter(board => Number(board.workspace_id) === Number(activeWorkspaceFilter)), cachedWorkspaces);
      } else {
        activeWorkspaceFilter = null;
        boardsTitle.textContent = "Todos los tableros";
        showAllBoardsButton.hidden = true;
        renderBoards(cachedBoards, cachedWorkspaces);
      }
      setStatus("Tus espacios y tableros están guardados localmente en FOOCUS.");
    } catch (error) { setStatus(error.message, true); }
  }

  showAllBoardsButton.addEventListener("click", () => {
    activeWorkspaceFilter = null;
    boardsTitle.textContent = "Todos los tableros";
    showAllBoardsButton.hidden = true;
    renderBoards(cachedBoards, cachedWorkspaces);
  });

  workspaceForm.addEventListener("submit", async event => {
    event.preventDefault();
    const values = new FormData(workspaceForm);
    const submit = workspaceForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await api("/api/workspaces", {
        method:"POST",
        body:JSON.stringify({
          name:values.get("name"), description:values.get("description"), color:values.get("color")
        })
      });
      workspaceForm.reset();
      setStatus("Espacio de trabajo creado.");
      await refresh();
    } catch (error) { setStatus(error.message, true); }
    finally { submit.disabled = false; }
  });

  boardForm.addEventListener("submit", async event => {
    event.preventDefault();
    const values = new FormData(boardForm);
    const submit = boardForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    const rawWorkspace = values.get("workspace_id");
    try {
      await api("/api/canvas", {
        method:"POST",
        body:JSON.stringify({
          title:values.get("title"), mode:values.get("mode"),
          workspace_id:rawWorkspace ? Number(rawWorkspace) : null
        })
      });
      boardForm.reset();
      setStatus("Tablero creado y guardado localmente.");
      await refresh();
    } catch (error) { setStatus(error.message, true); }
    finally { submit.disabled = false; }
  });

  window.FOOCUSCanvasRefresh = refresh;
  refresh();
})();
