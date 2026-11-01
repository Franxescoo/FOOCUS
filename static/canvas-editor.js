(() => {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const byId = id => document.getElementById(id);
  const editor = byId("canvas-editor");
  if (!editor) return;
  const catalog = byId("canvas-screen");
  const title = byId("canvas-editor-title");
  const modeLabel = byId("canvas-editor-mode-label");
  const hint = byId("canvas-editor-hint");
  const status = byId("canvas-save-indicator");
  const freeTools = byId("canvas-free-tools");
  const structuredTools = byId("canvas-structured-tools");
  const freeStage = byId("canvas-free-stage");
  const world = byId("canvas-free-world");
  const freeContent = byId("canvas-free-content");
  const zoomLabel = byId("canvas-zoom-label");
  const svg = byId("canvas-connection-layer");
  const structured = byId("canvas-structured-board");
  const undoButton = byId("canvas-undo");
  const redoButton = byId("canvas-redo");
  const saveButton = byId("canvas-save-now");
  const historyPanel = byId("canvas-history-panel");
  const historyList = byId("canvas-history-list");
  const attachmentElementSelect = byId("canvas-attachment-element");
  const attachmentFileForm = byId("canvas-attachment-file-form");
  const attachmentLinkForm = byId("canvas-attachment-link-form");
  const attachmentList = byId("canvas-attachment-list");
  let board = null;
  let state = {columns:[], elements:[], connections:[]};
  let undo = [];
  let redo = [];
  let selected = new Set();
  let dirty = false;
  let saving = false;
  let timer = null;
  let taskOptions = [];
  let changeRevision = 0;
  let zoom = 1;
  let viewportTimer = null;
  let restoringViewport = false;

  const clone = value => JSON.parse(JSON.stringify(value));
  const key = () => (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID().replace(/-/g, "")
    : "el" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);

  async function request(url, options = {}) {
    const method = options.method || "GET";
    const response = await fetch(url, {
      cache:"no-store", ...options,
      headers:{
        "Accept":"application/json",
        ...(options.body && !(options.body instanceof FormData) ? {"Content-Type":"application/json"} : {}),
        ...(method !== "GET" ? {"X-CSRF-Token":csrf} : {}),
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.message || "No se pudo completar la operación.");
    return data;
  }

  function refreshAttachmentElementOptions() {
    if (!board || !attachmentElementSelect) return;
    const previous = attachmentElementSelect.value;
    attachmentElementSelect.replaceChildren(new Option("Selecciona un elemento", ""));
    state.elements.forEach((item, index) => {
      const label = item.linked_task_title || item.content.title || ("Elemento " + (index + 1));
      const type = item.kind === "card" ? "Tarjeta" : (item.kind === "group" ? "Grupo" : "Nota");
      attachmentElementSelect.add(new Option(type + " · " + label, item.key));
    });
    if ([...attachmentElementSelect.options].some(option => option.value === previous)) attachmentElementSelect.value = previous;
    else if (state.elements.length) attachmentElementSelect.value = state.elements[0].key;
  }

  function renderAttachments(items) {
    attachmentList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "canvas-empty";
      empty.textContent = "Todavía no hay archivos ni enlaces adjuntos.";
      attachmentList.append(empty);
      return;
    }
    for (const item of items) {
      const row = document.createElement("article");
      row.className = "canvas-attachment-row";
      const info = document.createElement("div");
      info.className = "canvas-attachment-info";
      const name = document.createElement("strong");
      name.textContent = item.original_name;
      const detail = document.createElement("small");
      const size = Math.max(1, Math.round(Number(item.size_bytes || 0) / 1024));
      detail.textContent = (item.element_title || "Elemento eliminado") + " · " + (item.kind === "link" ? "Enlace externo" : size + " KB");
      info.append(name, detail);
      const open = document.createElement("a");
      open.href = item.kind === "link" ? item.url : item.download_url;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      open.textContent = item.kind === "link" ? "Abrir enlace" : "Abrir archivo";
      open.className = "focus-reset canvas-attachment-open";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "canvas-danger-button";
      remove.textContent = "Quitar";
      remove.addEventListener("click", async () => {
        if (!window.confirm("¿Quitar «" + item.original_name + "» del Canvas?")) return;
        try {
          await request("/api/canvas/" + board.id + "/attachments/" + item.id, {method:"DELETE"});
          await refreshAttachments();
        } catch (error) {
          byId("canvas-status").textContent = error.message;
          byId("canvas-status").classList.add("is-error");
        }
      });
      row.append(info, open, remove);
      attachmentList.append(row);
    }
  }

  async function refreshAttachments() {
    if (!board) return;
    try {
      const result = await request("/api/canvas/" + board.id + "/attachments");
      renderAttachments(result.items || []);
      refreshAttachmentElementOptions();
    } catch (error) { attachmentList.textContent = error.message; }
  }

  function scheduleViewportSave() {
    if (!board || board.mode !== "free" || restoringViewport) return;
    window.clearTimeout(viewportTimer);
    viewportTimer = window.setTimeout(async () => {
      if (!board || board.mode !== "free" || restoringViewport) return;
      try {
        await request("/api/canvas/" + board.id + "/viewport", {
          method:"PUT",
          body:JSON.stringify({x:Math.round(freeStage.scrollLeft), y:Math.round(freeStage.scrollTop), zoom})
        });
      } catch (error) {
        byId("canvas-status").textContent = "No se pudo guardar la vista del lienzo: " + error.message;
      }
    }, 350);
  }

  function applyZoom(nextZoom, preserveCenter = true, shouldSave = true) {
    const oldZoom = zoom;
    const next = Math.max(0.25, Math.min(2, Math.round(Number(nextZoom) * 100) / 100));
    if (!Number.isFinite(next) || next === oldZoom) return;
    const centerX = preserveCenter ? (freeStage.scrollLeft + freeStage.clientWidth / 2) / oldZoom : 0;
    const centerY = preserveCenter ? (freeStage.scrollTop + freeStage.clientHeight / 2) / oldZoom : 0;
    zoom = next;
    freeContent.style.transform = "scale(" + zoom + ")";
    zoomLabel.textContent = Math.round(zoom * 100) + "%";
    if (preserveCenter) {
      freeStage.scrollLeft = Math.max(0, centerX * zoom - freeStage.clientWidth / 2);
      freeStage.scrollTop = Math.max(0, centerY * zoom - freeStage.clientHeight / 2);
    }
    if (shouldSave) scheduleViewportSave();
  }

  function restoreViewport(viewport) {
    restoringViewport = true;
    const savedZoom = viewport && typeof viewport.zoom === "number" ? viewport.zoom : 1;
    zoom = 1;
    freeContent.style.transform = "scale(1)";
    zoomLabel.textContent = "100%";
    applyZoom(savedZoom, false, false);
    window.requestAnimationFrame(() => {
      freeStage.scrollLeft = Math.max(0, Number(viewport && viewport.x) || 0);
      freeStage.scrollTop = Math.max(0, Number(viewport && viewport.y) || 0);
      restoringViewport = false;
    });
  }

  freeStage.addEventListener("scroll", scheduleViewportSave, {passive:true});
  freeStage.addEventListener("wheel", event => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    applyZoom(zoom + (event.deltaY < 0 ? 0.1 : -0.1));
  }, {passive:false});
  freeStage.addEventListener("pointerdown", event => {
    const backgroundTarget = event.target === freeStage || event.target === freeContent || event.target === world || event.target === svg;
    if (!backgroundTarget || event.button !== 0) return;
    const startX = event.clientX, startY = event.clientY;
    const startLeft = freeStage.scrollLeft, startTop = freeStage.scrollTop;
    freeStage.classList.add("is-panning");
    freeStage.setPointerCapture(event.pointerId);
    function pan(moveEvent) {
      freeStage.scrollLeft = startLeft - (moveEvent.clientX - startX);
      freeStage.scrollTop = startTop - (moveEvent.clientY - startY);
    }
    function endPan(endEvent) {
      freeStage.classList.remove("is-panning");
      freeStage.removeEventListener("pointermove", pan);
      freeStage.removeEventListener("pointerup", endPan);
      freeStage.removeEventListener("pointercancel", endPan);
      if (freeStage.hasPointerCapture(endEvent.pointerId)) freeStage.releasePointerCapture(endEvent.pointerId);
      scheduleViewportSave();
    }
    freeStage.addEventListener("pointermove", pan);
    freeStage.addEventListener("pointerup", endPan, {once:true});
    freeStage.addEventListener("pointercancel", endPan, {once:true});
  });

  function setStatus(message, error = false) {
    status.textContent = message;
    status.classList.toggle("is-error", error);
    status.classList.toggle("is-dirty", dirty && !error);
  }
  function updateHistoryButtons() {
    undoButton.disabled = !undo.length;
    redoButton.disabled = !redo.length;
  }
  function remember() {
    undo.push(clone(state));
    if (undo.length > 80) undo.shift();
    redo = [];
    updateHistoryButtons();
  }
  function changed() {
    changeRevision += 1;
    dirty = true;
    setStatus("Cambios pendientes");
    window.clearTimeout(timer);
    timer = window.setTimeout(() => save(false), 1000);
  }
  async function save(manual) {
    if (!board || saving || !dirty) {
      if (manual && !dirty) setStatus("Todo guardado");
      return;
    }
    window.clearTimeout(timer);
    saving = true;
    const savedRevision = changeRevision;
    saveButton.disabled = true;
    setStatus("Guardando…");
    try {
      const result = await request("/api/canvas/" + board.id + "/content", {
        method:"PUT", body:JSON.stringify({...state, create_version: manual})
      });
      dirty = changeRevision !== savedRevision;
      setStatus("Guardado");
      byId("canvas-status").textContent = "Canvas guardado: " + result.counts.elements + " elementos.";
      if (result.version_number) await refreshHistory();
    } catch (error) {
      setStatus("Error al guardar", true);
      byId("canvas-status").textContent = error.message;
      byId("canvas-status").classList.add("is-error");
    } finally {
      saving = false;
      saveButton.disabled = false;
      if (dirty) timer = window.setTimeout(() => save(false), 1800);
    }
  }

  function editField(item, field, value) {
    if (item.content[field] === value) return;
    remember();
    item.content[field] = value;
    changed();
  }

  function renderConnections() {
    svg.replaceChildren();
    const items = new Map(state.elements.map(item => [item.key, item]));
    for (const link of state.connections) {
      const a = items.get(link.source);
      const b = items.get(link.target);
      if (!a || !b) continue;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(a.x + a.width / 2));
      line.setAttribute("y1", String(a.y + a.height / 2));
      line.setAttribute("x2", String(b.x + b.width / 2));
      line.setAttribute("y2", String(b.y + b.height / 2));
      line.setAttribute("class", "canvas-connection-line");
      svg.append(line);
    }
  }

  function selectFree(item, event) {
    if (event.ctrlKey || event.metaKey) {
      if (selected.has(item.key)) selected.delete(item.key);
      else selected.add(item.key);
    } else {
      selected.clear();
      selected.add(item.key);
    }
    world.querySelectorAll(".canvas-free-element").forEach(node => {
      node.classList.toggle("is-selected", selected.has(node.dataset.key));
    });
  }

  function renderFree() {
    world.replaceChildren();
    for (const item of state.elements) {
      const node = document.createElement("article");
      node.className = "canvas-free-element canvas-element-" + item.kind;
      node.dataset.key = item.key;
      node.classList.toggle("is-selected", selected.has(item.key));
      node.style.left = item.x + "px";
      node.style.top = item.y + "px";
      node.style.width = item.width + "px";
      node.style.height = item.height + "px";
      node.style.minHeight = item.height + "px";

      const grip = document.createElement("div");
      grip.className = "canvas-element-grip";
      grip.textContent = item.kind === "group" ? "Grupo · arrastrar" : "Arrastrar";
      node.append(grip);

      const heading = document.createElement("input");
      heading.type = "text";
      heading.maxLength = 160;
      heading.className = "canvas-element-title";
      heading.placeholder = "Título";
      heading.value = item.content.title || "";
      heading.addEventListener("change", () => editField(item, "title", heading.value));
      node.append(heading);

      const body = document.createElement("textarea");
      body.rows = 4;
      body.maxLength = 5000;
      body.className = "canvas-element-body";
      body.placeholder = "Escribe tus ideas aquí…";
      body.value = item.content.body || "";
      body.addEventListener("change", () => editField(item, "body", body.value));
      node.append(body);
      const resize = document.createElement("button");
      resize.type = "button";
      resize.className = "canvas-element-resize";
      resize.setAttribute("aria-label", "Redimensionar elemento");
      resize.title = "Arrastra para cambiar el tamaño";
      resize.addEventListener("pointerdown", event => {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX, startY = event.clientY;
        const startWidth = item.width, startHeight = item.height;
        remember();
        function resizeMove(moveEvent) {
          item.width = Math.max(160, Math.min(900, startWidth + (moveEvent.clientX - startX) / zoom));
          item.height = Math.max(110, Math.min(900, startHeight + (moveEvent.clientY - startY) / zoom));
          node.style.width = item.width + "px";
          node.style.height = item.height + "px";
          node.style.minHeight = item.height + "px";
          renderConnections();
        }
        function resizeEnd() {
          window.removeEventListener("pointermove", resizeMove);
          window.removeEventListener("pointerup", resizeEnd);
          if (item.width !== startWidth || item.height !== startHeight) changed();
        }
        window.addEventListener("pointermove", resizeMove);
        window.addEventListener("pointerup", resizeEnd, {once:true});
      });
      node.append(resize);

      node.addEventListener("click", event => selectFree(item, event));
      node.addEventListener("pointerdown", event => {
        if (event.button !== 0 || event.target.closest("input,textarea,button")) return;
        const sx = event.clientX, sy = event.clientY, ix = item.x, iy = item.y;
        remember();
        selectFree(item, event);
        node.classList.add("is-dragging");
        function move(moveEvent) {
          item.x = Math.max(0, Math.min(100000, ix + (moveEvent.clientX - sx) / zoom));
          item.y = Math.max(0, Math.min(100000, iy + (moveEvent.clientY - sy) / zoom));
          node.style.left = item.x + "px";
          node.style.top = item.y + "px";
          renderConnections();
        }
        function end() {
          node.classList.remove("is-dragging");
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", end);
          if (item.x !== ix || item.y !== iy) changed();
        }
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", end, {once:true});
      });
      world.append(node);
    }
    renderConnections();
    refreshAttachmentElementOptions();
  }

  function addFree(kind) {
    const n = state.elements.length;
    remember();
    state.elements.push({
      key:key(), kind, column_key:null,
      x:100 + (n % 7) * 35, y:90 + (n % 9) * 30,
      width:kind === "group" ? 320 : 250,
      height:kind === "group" ? 220 : 165,
      task_id:null,
      content:{title:kind === "group" ? "Nuevo grupo" : (kind === "text" ? "Bloque de texto" : "Nueva nota"), body:""}
    });
    selected.clear();
    renderFree();
    changed();
  }

  function connectSelected() {
    const keys = [...selected];
    if (keys.length !== 2) {
      byId("canvas-status").textContent = "Selecciona exactamente dos elementos con Ctrl/Cmd + clic.";
      return;
    }
    if (state.connections.some(item =>
      (item.source === keys[0] && item.target === keys[1]) ||
      (item.source === keys[1] && item.target === keys[0]))) return;
    remember();
    state.connections.push({key:key(), source:keys[0], target:keys[1], label:""});
    renderConnections();
    changed();
  }

  function duplicateSelected() {
    const originals = state.elements.filter(item => selected.has(item.key));
    if (!originals.length) {
      byId("canvas-status").textContent = "Selecciona al menos un elemento para duplicar.";
      return;
    }
    remember();
    const copies = originals.map((item, index) => {
      const copy = clone(item);
      copy.key = key();
      copy.x = Math.max(0, item.x + 28 + index * 12);
      copy.y = Math.max(0, item.y + 28 + index * 12);
      copy.task_id = null;
      copy.task_snapshot_title = "";
      copy.linked_task_title = "";
      copy.linked_task_priority = "";
      copy.linked_task_due_date = "";
      copy.linked_task_completed = null;
      copy.content.title = (copy.content.title || "Elemento") + " (copia)";
      return copy;
    });
    state.elements.push(...copies);
    selected = new Set(copies.map(item => item.key));
    renderFree();
    changed();
  }

  function deleteSelected() {
    if (!selected.size) return;
    remember();
    const keys = new Set(selected);
    state.elements = state.elements.filter(item => !keys.has(item.key));
    state.connections = state.connections.filter(item => !keys.has(item.source) && !keys.has(item.target));
    selected.clear();
    renderFree();
    changed();
  }

  function getFieldValue(item, field) {
    if (!item.task_id) return item.content[field] || "";
    if (field === "title") return item.linked_task_title || item.content.title || "";
    if (field === "priority") return item.linked_task_priority || item.content.priority || "Media";
    if (field === "due_date") return item.linked_task_due_date || "";
    if (field === "status") return item.linked_task_completed ? "Completada" : "Pendiente";
    return item.content[field] || "";
  }

  async function updateLinkedTask(item, field, value) {
    const task = taskOptions.find(option => Number(option.id) === Number(item.task_id));
    if (!task) {
      byId("canvas-status").textContent = "La tarea global ya no está disponible. Desvincúlala para convertir esta tarjeta en una tarea propia."; 
      return;
    }
    try {
      if (field === "status") {
        const completed = value === "Completada";
        await request("/api/tasks/" + task.id + "/completion", {
          method:"PUT", body:JSON.stringify({completed})
        });
        task.completed = completed ? 1 : 0;
        item.linked_task_completed = completed;
        item.content.status = value;
      } else {
        const payload = {
          title: field === "title" ? value : task.title,
          priority: field === "priority" ? value : task.priority,
          due_date: field === "due_date" ? value : (task.due_date || ""),
          planned_date: task.planned_date || "",
          subject: task.subject || "",
          estimated_minutes: task.estimated_minutes || 30
        };
        const result = await request("/api/tasks/" + task.id, {
          method:"PATCH", body:JSON.stringify(payload)
        });
        Object.assign(task, result.task);
        item.linked_task_title = result.task.title;
        item.linked_task_priority = result.task.priority;
        item.linked_task_due_date = result.task.due_date || "";
        item.task_snapshot_title = result.task.title;
        item.content[field] = value;
      }
      changed();
      if (board.mode === "structured") renderStructured();
      byId("canvas-status").textContent = "Tarea global actualizada desde Canvas.";
    } catch (error) {
      byId("canvas-status").textContent = error.message;
      byId("canvas-status").classList.add("is-error");
    }
  }

  function inputField(item, field, label, type, choices) {
    let control;
    if (type === "select") {
      control = document.createElement("select");
      for (const choice of choices) control.add(new Option(choice, choice));
      control.value = getFieldValue(item, field) || choices[0];
    } else if (type === "textarea") {
      control = document.createElement("textarea");
      control.rows = 3;
      control.maxLength = 2000;
      control.value = getFieldValue(item, field);
      control.placeholder = label;
    } else {
      control = document.createElement("input");
      control.type = type;
      control.value = getFieldValue(item, field);
      if (type === "text") control.maxLength = field === "title" ? 160 : 2000;
    }
    control.setAttribute("aria-label", label);
    control.addEventListener("change", () => {
      if (item.task_id && ["title","priority","due_date","status"].includes(field)) {
        updateLinkedTask(item, field, control.value);
      } else editField(item, field, control.value);
    });
    return control;
  }

  function renderStructured() {
    structured.replaceChildren();
    for (const column of state.columns) {
      const section = document.createElement("section");
      section.className = "canvas-column";
      section.dataset.columnKey = column.key;
      const header = document.createElement("div");
      header.className = "canvas-column-header";
      const name = document.createElement("input");
      name.type = "text";
      name.maxLength = 60;
      name.value = column.title;
      name.setAttribute("aria-label", "Nombre de columna");
      name.addEventListener("change", () => {
        if (!name.value.trim() || name.value.trim() === column.title) return;
        remember();
        column.title = name.value.trim();
        changed();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "canvas-column-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "Eliminar columna " + column.title);
      remove.addEventListener("click", () => removeColumn(column));
      header.append(name, remove);
      section.append(header);

      const list = document.createElement("div");
      list.className = "canvas-column-cards";
      const cards = state.elements.filter(item => item.column_key === column.key);
      for (const card of cards) {
        const article = document.createElement("article");
        article.className = "canvas-structured-card";
        article.draggable = true;
        article.addEventListener("dragstart", event => {
          event.dataTransfer.setData("text/plain", card.key);
          event.dataTransfer.effectAllowed = "move";
        });
        const linkRow = document.createElement("label");
        linkRow.className = "canvas-task-link";
        linkRow.textContent = "Vincular tarea de FOOCUS";
        const linkSelect = document.createElement("select");
        linkSelect.setAttribute("aria-label", "Vincular tarjeta con tarea global");
        linkSelect.add(new Option("Tarea propia de Canvas", ""));
        for (const task of taskOptions) {
          const suffix = task.completed ? " · Completada" : "";
          linkSelect.add(new Option(task.title + suffix, String(task.id)));
        }
        linkSelect.value = card.task_id === null ? "" : String(card.task_id);
        linkSelect.addEventListener("change", () => {
          remember();
          if (!linkSelect.value) {
            if (card.task_id) {
              card.content.title = card.linked_task_title || card.content.title;
              card.content.priority = card.linked_task_priority || card.content.priority || "Media";
              card.content.due_date = card.linked_task_due_date || "";
              card.content.status = card.linked_task_completed ? "Completada" : "Pendiente";
            }
            card.task_id = null;
            card.task_snapshot_title = "";
            card.linked_task_title = "";
            card.linked_task_priority = "";
            card.linked_task_due_date = "";
            card.linked_task_completed = null;
          } else {
            const task = taskOptions.find(option => Number(option.id) === Number(linkSelect.value));
            if (!task) return;
            card.task_id = task.id;
            card.task_snapshot_title = task.title;
            card.linked_task_title = task.title;
            card.linked_task_priority = task.priority;
            card.linked_task_due_date = task.due_date || "";
            card.linked_task_completed = Boolean(task.completed);
            card.content.title = task.title;
            card.content.priority = task.priority;
            card.content.due_date = task.due_date || "";
            card.content.status = task.completed ? "Completada" : "Pendiente";
          }
          renderStructured();
          changed();
        });
        linkRow.append(linkSelect);
        article.append(linkRow);
        if (card.task_snapshot_title && !card.task_id) {
          const orphanNote = document.createElement("small");
          orphanNote.className = "canvas-orphan-task-note";
          orphanNote.textContent = "La tarea global original ya no existe. El contenido se conservó."; 
          article.append(orphanNote);
        }
        article.append(inputField(card, "title", "Título", "text"));
        article.append(inputField(card, "description", "Descripción", "textarea"));
        const meta = document.createElement("div");
        meta.className = "canvas-card-meta";
        meta.append(
          inputField(card, "priority", "Prioridad", "select", ["Media","Baja","Alta"]),
          inputField(card, "status", "Estado", "select", card.task_id ? ["Pendiente","Completada"] : ["Pendiente","En curso","En revisión","Completada"]),
          inputField(card, "due_date", "Fecha límite", "date")
        );
        article.append(meta);

        const actions = document.createElement("div");
        actions.className = "canvas-card-actions";
        const target = document.createElement("select");
        target.setAttribute("aria-label", "Mover tarjeta a otra columna");
        for (const option of state.columns) target.add(new Option(option.title, option.key));
        target.value = card.column_key;
        target.addEventListener("change", () => {
          if (target.value === card.column_key) return;
          remember();
          card.column_key = target.value;
          renderStructured();
          changed();
        });
        actions.append(target);
        if (!card.task_id) {
          const convert = document.createElement("button");
          convert.type = "button";
          convert.className = "focus-reset";
          convert.textContent = card.task_snapshot_title ? "Crear nueva tarea global" : "Convertir en tarea global";
          convert.addEventListener("click", async () => {
            if (dirty) {
              await save(false);
              if (dirty) return;
            }
            convert.disabled = true;
            try {
              const result = await request("/api/canvas/" + board.id + "/elements/" + card.key + "/convert-task", {
                method:"POST", body:JSON.stringify({})
              });
              const task = result.task;
              remember();
              card.task_id = task.id;
              card.task_snapshot_title = task.title;
              card.linked_task_title = task.title;
              card.linked_task_priority = task.priority;
              card.linked_task_due_date = task.due_date || "";
              card.linked_task_completed = Boolean(task.completed);
              card.content.title = task.title;
              card.content.priority = task.priority;
              card.content.due_date = task.due_date || "";
              card.content.status = task.completed ? "Completada" : "Pendiente";
              taskOptions = taskOptions.filter(item => Number(item.id) !== Number(task.id));
              taskOptions.push(task);
              changed();
              renderStructured();
              await save(true);
              byId("canvas-status").textContent = result.already_linked
                ? "Esta tarjeta ya estaba vinculada a una tarea global."
                : "Tarjeta convertida en tarea global. Ya aparece en Tareas y puede usarse en el calendario y planificador.";
            } catch (error) {
              byId("canvas-status").textContent = error.message;
              byId("canvas-status").classList.add("is-error");
            } finally { convert.disabled = false; }
          });
          actions.append(convert);
        }
        const duplicate = document.createElement("button");
        duplicate.type = "button";
        duplicate.className = "focus-reset";
        duplicate.textContent = "Duplicar";
        duplicate.addEventListener("click", () => {
          remember();
          const copy = clone(card);
          copy.key = key();
          copy.content.title = (card.task_id ? (card.linked_task_title || copy.content.title) : copy.content.title || "Tarjeta") + " (copia)";
          copy.task_id = null;
          copy.task_snapshot_title = "";
          copy.linked_task_title = "";
          copy.linked_task_priority = "";
          copy.linked_task_due_date = "";
          copy.linked_task_completed = null;
          state.elements.push(copy);
          renderStructured();
          changed();
        });
        const removeCard = document.createElement("button");
        removeCard.type = "button";
        removeCard.className = "canvas-danger-button";
        removeCard.textContent = "Eliminar";
        removeCard.addEventListener("click", () => {
          if (!window.confirm("¿Eliminar esta tarjeta?")) return;
          remember();
          state.elements = state.elements.filter(item => item.key !== card.key);
          renderStructured();
          changed();
        });
        actions.append(duplicate, removeCard);
        article.append(actions);
        list.append(article);
      }
      section.append(list);
      const addCard = document.createElement("button");
      addCard.type = "button";
      addCard.className = "primary-button canvas-add-card";
      addCard.textContent = "+ Tarjeta";
      addCard.addEventListener("click", () => {
        remember();
        state.elements.push({
          key:key(), kind:"card", column_key:column.key,
          x:0, y:0, width:280, height:190, task_id:null,
          content:{title:"Nueva tarea", description:"", priority:"Media", due_date:"", status:"Pendiente"}
        });
        renderStructured();
        changed();
      });
      section.append(addCard);
      section.addEventListener("dragover", event => event.preventDefault());
      section.addEventListener("drop", event => {
        event.preventDefault();
        const elementKey = event.dataTransfer.getData("text/plain");
        const card = state.elements.find(item => item.key === elementKey);
        if (!card || card.column_key === column.key) return;
        remember();
        card.column_key = column.key;
        renderStructured();
        changed();
      });
      structured.append(section);
    }
    refreshAttachmentElementOptions();
  }

  function removeColumn(column) {
    if (state.columns.length <= 1) {
      byId("canvas-status").textContent = "Un Canvas estructurado debe conservar al menos una columna.";
      return;
    }
    const remaining = state.columns.filter(item => item.key !== column.key);
    const cards = state.elements.filter(item => item.column_key === column.key);
    let destination = null;
    if (cards.length) {
      const options = remaining.map((item, index) => (index + 1) + ". " + item.title).join("\n");
      const answer = window.prompt("La columna tiene tarjetas. Indica dónde moverlas:\n" + options, "1");
      if (answer === null) return;
      const index = Number(answer) - 1;
      if (!Number.isInteger(index) || index < 0 || index >= remaining.length) {
        byId("canvas-status").textContent = "No se modificó la columna: selecciona un número válido.";
        return;
      }
      destination = remaining[index];
    } else if (!window.confirm("¿Eliminar la columna «" + column.title + "»?")) return;
    remember();
    if (destination) cards.forEach(card => { card.column_key = destination.key; });
    state.columns = remaining;
    renderStructured();
    changed();
  }

  function renderHistory(items) {
    historyList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "canvas-empty";
      empty.textContent = "Todavía no hay versiones. Se creará una al guardar por primera vez.";
      historyList.append(empty);
      return;
    }
    for (const version of items) {
      const row = document.createElement("article");
      row.className = "canvas-history-row";
      const copy = document.createElement("div");
      const description = document.createElement("strong");
      description.textContent = "Versión " + version.version_number + " · " + version.description;
      const created = document.createElement("small");
      created.textContent = version.created_at;
      copy.append(description, created);
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "focus-reset";
      restore.textContent = "Restaurar";
      restore.addEventListener("click", () => restoreVersion(version));
      row.append(copy, restore);
      historyList.append(row);
    }
  }

  async function refreshHistory() {
    if (!board) return;
    try {
      const result = await request("/api/canvas/" + board.id + "/history");
      renderHistory(result.items || []);
    } catch (error) {
      historyList.textContent = error.message;
    }
  }

  async function restoreVersion(version) {
    if (dirty && !window.confirm("Hay cambios sin guardar. ¿Descartarlos y restaurar la versión seleccionada?")) return;
    if (!window.confirm("¿Restaurar la versión " + version.version_number + "? Se conservarán las versiones posteriores.")) return;
    try {
      setStatus("Restaurando versión…");
      await request("/api/canvas/" + board.id + "/history/" + version.id + "/restore", {
        method:"POST", body:JSON.stringify({})
      });
      const result = await request("/api/canvas/" + board.id + "/content");
      state = {
        columns:result.columns || [],
        elements:(result.elements || []).map(element => ({
          key:element.key, kind:element.kind, column_key:element.column_key,
          x:element.x, y:element.y, width:element.width, height:element.height,
          task_id:element.task_id, content:element.content || {},
          task_snapshot_title:element.task_snapshot_title || "",
          linked_task_title:element.linked_task_title || "",
          linked_task_priority:element.linked_task_priority || "",
          linked_task_due_date:element.linked_task_due_date || "",
          linked_task_planned_date:element.linked_task_planned_date || "",
          linked_task_estimated_minutes:element.linked_task_estimated_minutes || 30,
          linked_task_subject:element.linked_task_subject || "",
          linked_task_completed:element.linked_task_completed
        })),
        connections:result.connections || []
      };
      dirty = false;
      undo = [];
      redo = [];
      selected.clear();
      if (board.mode === "free") renderFree(); else renderStructured();
      updateHistoryButtons();
      setStatus("Versión restaurada y guardada.");
      await refreshHistory();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function openBoard(item) {
    try {
      const result = await Promise.all([
        request("/api/canvas/" + item.id),
        request("/api/canvas/" + item.id + "/content"),
        request("/api/canvas/task-options"),
        request("/api/canvas/" + item.id + "/history"),
        request("/api/canvas/" + item.id + "/attachments")
      ]);
      taskOptions = result[2].items || [];
      let savedViewport = {};
      try { savedViewport = JSON.parse(result[0].item.viewport_json || "{}"); } catch (error) { savedViewport = {}; }
      board = item;
      state = {
        columns:result[1].columns || [],
        elements:(result[1].elements || []).map(element => ({
          key:element.key, kind:element.kind, column_key:element.column_key,
          x:element.x, y:element.y, width:element.width, height:element.height,
          task_id:element.task_id, content:element.content || {},
          task_snapshot_title:element.task_snapshot_title || "",
          linked_task_title:element.linked_task_title || "",
          linked_task_priority:element.linked_task_priority || "",
          linked_task_due_date:element.linked_task_due_date || "",
          linked_task_planned_date:element.linked_task_planned_date || "",
          linked_task_estimated_minutes:element.linked_task_estimated_minutes || 30,
          linked_task_subject:element.linked_task_subject || "",
          linked_task_completed:element.linked_task_completed
        })),
        connections:result[1].connections || []
      };
      if (board.mode === "structured" && !state.columns.length) {
        state.columns = [
          {key:"todo",title:"Por hacer"},
          {key:"doing",title:"En curso"},
          {key:"done",title:"Hecho"}
        ];
        dirty = true;
      } else dirty = false;
      undo = [];
      redo = [];
      selected.clear();
      title.textContent = result[0].item.title;
      modeLabel.textContent = board.mode === "structured" ? "CANVAS ESTRUCTURADO" : "CANVAS LIBRE";
      freeTools.hidden = board.mode !== "free";
      structuredTools.hidden = board.mode !== "structured";
      freeStage.hidden = board.mode !== "free";
      structured.hidden = board.mode !== "structured";
      hint.textContent = board.mode === "structured"
        ? "Arrastra las tarjetas entre columnas o usa el selector de ubicación. Los cambios se guardan automáticamente."
        : "Arrastra los bloques para organizarlos. Usa Ctrl/Cmd + clic para seleccionar varios elementos y crear conexiones.";
      catalog.hidden = true;
      editor.hidden = false;
      if (board.mode === "free") {
        renderFree();
        restoreViewport(savedViewport);
      } else renderStructured();
      historyPanel.hidden = true;
      renderHistory(result[3].items || []);
      renderAttachments(result[4].items || []);
      refreshAttachmentElementOptions();
      updateHistoryButtons();
      setStatus(dirty ? "Cambios pendientes" : "Guardado");
      window.scrollTo({top:0,behavior:"smooth"});
      if (dirty) changed();
    } catch (error) {
      byId("canvas-status").textContent = error.message;
      byId("canvas-status").classList.add("is-error");
    }
  }

  function closeEditor() {
    if (dirty && !window.confirm("Hay cambios pendientes. ¿Guardar antes de volver?")) return;
    if (dirty) {
      save(true).then(() => {
        if (!dirty) finishClose();
      });
    } else finishClose();
  }
  function finishClose() {
    window.clearTimeout(timer);
    editor.hidden = true;
    catalog.hidden = false;
    board = null;
    window.FOOCUSCanvasRefresh?.();
    window.scrollTo({top:0,behavior:"smooth"});
  }

  byId("canvas-history-toggle").addEventListener("click", async () => {
    historyPanel.hidden = !historyPanel.hidden;
    if (!historyPanel.hidden) await refreshHistory();
  });
  byId("canvas-history-close").addEventListener("click", () => { historyPanel.hidden = true; });
  attachmentFileForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!board || !attachmentElementSelect.value) {
      byId("canvas-status").textContent = "Crea o selecciona un elemento antes de adjuntar un archivo.";
      return;
    }
    if (dirty) { await save(false); if (dirty) return; }
    const fileInput = byId("canvas-attachment-file");
    if (!fileInput.files || !fileInput.files.length) return;
    const formData = new FormData();
    formData.append("element_key", attachmentElementSelect.value);
    formData.append("file", fileInput.files[0]);
    const submit = attachmentFileForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await request("/api/canvas/" + board.id + "/attachments", {method:"POST", body:formData});
      attachmentFileForm.reset();
      byId("canvas-status").textContent = "Archivo adjuntado localmente.";
      await refreshAttachments();
    } catch (error) {
      byId("canvas-status").textContent = error.message;
      byId("canvas-status").classList.add("is-error");
    } finally { submit.disabled = false; }
  });

  attachmentLinkForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!board || !attachmentElementSelect.value) {
      byId("canvas-status").textContent = "Crea o selecciona un elemento antes de agregar un enlace.";
      return;
    }
    if (dirty) { await save(false); if (dirty) return; }
    const url = byId("canvas-attachment-url").value.trim();
    const submit = attachmentLinkForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await request("/api/canvas/" + board.id + "/attachments", {
        method:"POST", body:JSON.stringify({element_key:attachmentElementSelect.value, url})
      });
      attachmentLinkForm.reset();
      byId("canvas-status").textContent = "Enlace agregado.";
      await refreshAttachments();
    } catch (error) {
      byId("canvas-status").textContent = error.message;
      byId("canvas-status").classList.add("is-error");
    } finally { submit.disabled = false; }
  });

  byId("canvas-editor-back").addEventListener("click", closeEditor);
  byId("canvas-add-note").addEventListener("click", () => addFree("note"));
  byId("canvas-add-text").addEventListener("click", () => addFree("text"));
  byId("canvas-add-group").addEventListener("click", () => addFree("group"));
  byId("canvas-connect-elements").addEventListener("click", connectSelected);
  byId("canvas-zoom-out").addEventListener("click", () => applyZoom(zoom - 0.1));
  byId("canvas-zoom-in").addEventListener("click", () => applyZoom(zoom + 0.1));
  byId("canvas-zoom-fit").addEventListener("click", () => {
    if (!state.elements.length) {
      applyZoom(0.8, false);
      freeStage.scrollLeft = 0;
      freeStage.scrollTop = 0;
      scheduleViewportSave();
      return;
    }
    const maxX = Math.max(500, ...state.elements.map(item => item.x + item.width + 50));
    const maxY = Math.max(350, ...state.elements.map(item => item.y + item.height + 50));
    const fit = Math.min(2, (freeStage.clientWidth - 50) / maxX, (freeStage.clientHeight - 50) / maxY);
    applyZoom(Math.max(0.25, fit), false);
    freeStage.scrollLeft = 0;
    freeStage.scrollTop = 0;
    scheduleViewportSave();
  });
  byId("canvas-delete-element").addEventListener("click", deleteSelected);
  byId("canvas-duplicate-element").addEventListener("click", duplicateSelected);
  byId("canvas-add-column").addEventListener("click", () => {
    const name = window.prompt("Nombre de la nueva columna:", "Nueva columna");
    if (name === null || !name.trim()) return;
    if (name.trim().length > 60) {
      byId("canvas-status").textContent = "El nombre de la columna no puede superar 60 caracteres.";
      return;
    }
    remember();
    state.columns.push({key:key(),title:name.trim()});
    renderStructured();
    changed();
  });
  undoButton.addEventListener("click", () => {
    if (!undo.length) return;
    redo.push(clone(state));
    state = undo.pop();
    selected.clear();
    if (board.mode === "free") renderFree(); else renderStructured();
    updateHistoryButtons();
    changed();
  });
  redoButton.addEventListener("click", () => {
    if (!redo.length) return;
    undo.push(clone(state));
    state = redo.pop();
    if (board.mode === "free") renderFree(); else renderStructured();
    updateHistoryButtons();
    changed();
  });
  saveButton.addEventListener("click", () => save(true));
  window.FOOCUSCanvasOpenEditor = openBoard;
  window.FOOCUSCanvasSyncScreen = screen => {
    if (screen !== "canvas") {
      editor.hidden = true;
      catalog.hidden = true;
    } else if (board) {
      editor.hidden = false;
      catalog.hidden = true;
    } else {
      editor.hidden = true;
      catalog.hidden = false;
    }
  };
})();
