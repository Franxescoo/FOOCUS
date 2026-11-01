(() => {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const dayInputs = [...document.querySelectorAll("[data-available-day]")];
  const widgetInputs = [...document.querySelectorAll("[data-dashboard-widget]")];
  const horizon = document.getElementById("planner-horizon");
  const generateButton = document.getElementById("generate-plan");
  const applyButton = document.getElementById("apply-plan");
  const plannerStatus = document.getElementById("planner-status");
  const plannerSummary = document.getElementById("planner-summary");
  const plannerResults = document.getElementById("planner-results");
  const savedPlan = document.getElementById("saved-plan");
  const saveButton = document.getElementById("save-productivity-profile");
  const resetButton = document.getElementById("reset-productivity-profile");
  const profileStatus = document.getElementById("profile-save-status");
  const fields = {
    adaptive: document.getElementById("profile-adaptive"),
    start: document.getElementById("profile-start-time"),
    end: document.getElementById("profile-end-time"),
    session: document.getElementById("profile-session-minutes"),
    rest: document.getElementById("profile-break-minutes"),
    capacity: document.getElementById("profile-daily-capacity"),
    accent: document.getElementById("profile-accent"),
    compact: document.getElementById("profile-compact")
  };
  const insightSample = document.getElementById("insights-sample");
  const insightMetrics = document.getElementById("insight-metrics");
  const recommendations = document.getElementById("insight-recommendations");
  const defaults = {
    adaptive_enabled:true, available_days:[0,1,2,3,4], start_time:"16:00", end_time:"20:00",
    session_minutes:45, break_minutes:10, daily_capacity_minutes:180, planning_horizon_days:7,
    accent:"violet", compact_mode:false,
    dashboard_widgets:["welcome","summary","starter","weekly","analytics"]
  };
  let proposal = null;

  async function api(url, options = {}) {
    const response = await fetch(url, {
      cache:"no-store", ...options,
      headers:{
        "Accept":"application/json",
        ...(options.body ? {"Content-Type":"application/json"} : {}),
        ...(options.method && options.method !== "GET" ? {"X-CSRF-Token":csrfToken} : {}),
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.message || "No se pudo completar la operación.");
    return data;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
    })[c]);
  }

  function applyProfile(profile) {
    const value = {...defaults, ...profile};
    document.documentElement.dataset.accent = value.accent;
    document.documentElement.classList.toggle("compact-mode", Boolean(value.compact_mode));
    document.body.dataset.sessionMinutes = String(value.session_minutes);
    document.body.dataset.breakMinutes = String(value.break_minutes);
    document.querySelectorAll("[data-widget]").forEach(element => {
      element.classList.toggle("widget-is-hidden", !value.dashboard_widgets.includes(element.dataset.widget));
    });
    dayInputs.forEach(input => { input.checked = value.available_days.includes(Number(input.value)); });
    widgetInputs.forEach(input => { input.checked = value.dashboard_widgets.includes(input.value); });
    fields.adaptive.checked = value.adaptive_enabled;
    fields.start.value = value.start_time;
    fields.end.value = value.end_time;
    fields.session.value = String(value.session_minutes);
    fields.rest.value = String(value.break_minutes);
    fields.capacity.value = String(value.daily_capacity_minutes);
    fields.accent.value = value.accent;
    fields.compact.checked = value.compact_mode;
    horizon.value = String(value.planning_horizon_days);
    window.dispatchEvent(new CustomEvent("foocus:profile-updated", {
      detail:{sessionMinutes:value.session_minutes,breakMinutes:value.break_minutes}
    }));
  }

  function collectProfile() {
    return {
      adaptive_enabled:fields.adaptive.checked,
      available_days:dayInputs.filter(input => input.checked).map(input => Number(input.value)),
      start_time:fields.start.value, end_time:fields.end.value,
      session_minutes:Number(fields.session.value), break_minutes:Number(fields.rest.value),
      daily_capacity_minutes:Number(fields.capacity.value), planning_horizon_days:Number(horizon.value),
      accent:fields.accent.value, compact_mode:fields.compact.checked,
      dashboard_widgets:widgetInputs.filter(input => input.checked).map(input => input.value)
    };
  }

  function renderPlan(container, items, emptyText) {
    if (!container) return;
    if (!Array.isArray(items) || !items.length) {
      container.innerHTML = '<p class="plus-empty">' + escapeHtml(emptyText) + '</p>';
      return;
    }
    container.innerHTML = items.map(item => {
      const day = new Date(item.planned_date + "T12:00:00");
      const label = day.toLocaleDateString("es-CL", {weekday:"short",day:"numeric",month:"short"});
      const startParts = String(item.start_time || "00:00").split(":").map(Number);
      const endMinutes = startParts[0]*60 + startParts[1] + Number(item.duration_minutes || 0);
      const endTime = item.end_time || (String(Math.floor(endMinutes/60)).padStart(2,"0")+":"+String(endMinutes%60).padStart(2,"0"));
      return '<article class="plus-plan-item"><div class="plus-plan-time"><strong>' + escapeHtml(item.start_time || "—") +
        '</strong><small>' + escapeHtml(endTime) + '</small></div><div class="plus-plan-copy"><strong>' +
        escapeHtml(item.task_title || item.title) + '</strong><span>' + escapeHtml(label) + ' · ' +
        escapeHtml(item.duration_minutes) + ' min' + (item.subject ? ' · ' + escapeHtml(item.subject) : '') +
        '</span>' + (item.due_date ? '<small>Entrega: ' + escapeHtml(item.due_date) + '</small>' : '') +
        '</div><span class="priority priority-' + escapeHtml(String(item.priority || "Media").toLowerCase()) +
        '">' + escapeHtml(item.priority || "Media") + '</span></article>';
    }).join("");
  }

  function unscheduledHtml(items) {
    if (!Array.isArray(items) || !items.length) return "";
    return '<div class="plus-unscheduled"><strong>Actividades que requieren atención</strong>' +
      items.map(item => '<p>' + escapeHtml(item.title) +
        (item.remaining_minutes ? ' · ' + escapeHtml(item.remaining_minutes) + ' min pendientes' : '') +
        ' — ' + escapeHtml(item.reason) + '</p>').join("") + '</div>';
  }

  async function loadSavedPlan() {
    try {
      const data = await api("/api/productivity/plan");
      renderPlan(savedPlan, data.items, "Todavía no tienes sesiones sugeridas guardadas.");
    } catch (error) {
      savedPlan.innerHTML = '<p class="plus-empty">' + escapeHtml(error.message) + '</p>';
    }
  }

  async function generatePlan() {
    generateButton.disabled = true;
    applyButton.disabled = true;
    plannerStatus.textContent = "Analizando tareas, fechas y disponibilidad…";
    plannerSummary.hidden = true;
    try {
      proposal = await api("/api/productivity/plan", {
        method:"POST", body:JSON.stringify({horizon_days:Number(horizon.value)})
      });
      renderPlan(plannerResults, proposal.items, "No encontramos sesiones que se puedan programar. Revisa tareas y disponibilidad.");
      plannerSummary.hidden = false;
      plannerSummary.textContent = proposal.scheduled_sessions + " sesiones · " +
        proposal.scheduled_minutes + " minutos distribuidos en " + proposal.horizon_days + " días.";
      const warning = unscheduledHtml(proposal.unscheduled);
      if (warning) plannerResults.insertAdjacentHTML("beforeend", warning);
      applyButton.disabled = !proposal.items.length;
      plannerStatus.textContent = proposal.items.length
        ? "Esta es una propuesta. Tu calendario todavía no ha cambiado."
        : "No se generaron sesiones. Puedes ajustar tus preferencias y volver a intentarlo.";
    } catch (error) {
      proposal = null;
      plannerResults.replaceChildren();
      plannerStatus.textContent = error.message;
    } finally {
      generateButton.disabled = false;
    }
  }

  async function acceptPlan() {
    if (!proposal?.items?.length) return;
    applyButton.disabled = true;
    plannerStatus.textContent = "Guardando la propuesta y sincronizándola con tu calendario…";
    try {
      const result = await api("/api/productivity/plan/apply", {
        method:"POST", body:JSON.stringify({horizon_days:proposal.horizon_days})
      });
      plannerStatus.textContent = result.message + " (" + result.count + " sesiones).";
      renderPlan(plannerResults, result.items, "No hay sesiones sugeridas.");
      const warning = unscheduledHtml(result.unscheduled);
      if (warning) plannerResults.insertAdjacentHTML("beforeend", warning);
      proposal = null;
      await loadSavedPlan();
    } catch (error) {
      plannerStatus.textContent = error.message;
      applyButton.disabled = false;
    }
  }

  async function saveProfile() {
    saveButton.disabled = true;
    profileStatus.textContent = "Guardando preferencias…";
    try {
      const result = await api("/api/productivity/profile", {
        method:"PUT", body:JSON.stringify(collectProfile())
      });
      applyProfile(result.profile);
      profileStatus.textContent = result.message;
      await loadInsights();
    } catch (error) {
      profileStatus.textContent = error.message;
    } finally {
      saveButton.disabled = false;
    }
  }

  async function loadInsights() {
    try {
      const data = await api("/api/productivity/insights");
      insightSample.textContent = data.sample_size + " sesiones · últimos 60 días";
      const metrics = data.metrics || {};
      insightMetrics.innerHTML =
        '<article><small>Promedio por sesión</small><strong>' +
        (metrics.average_session_minutes ? escapeHtml(metrics.average_session_minutes) + " min" : "—") +
        '</strong></article><article><small>Horario más frecuente</small><strong>' +
        escapeHtml(metrics.best_period || "Sin patrón todavía") +
        '</strong></article><article><small>Tiempo real / estimado</small><strong>' +
        (metrics.estimate_ratio === null ? "—" : escapeHtml(Math.round(metrics.estimate_ratio*100)) + "%") +
        '</strong></article>';
      recommendations.innerHTML = (data.recommendations || []).map(item => '<p>' + escapeHtml(item) + '</p>').join("");
    } catch (error) {
      insightSample.textContent = "No disponible";
      recommendations.textContent = error.message;
    }
  }

  function bindDeleteConfirmations() {
    document.querySelectorAll(".delete-task-form").forEach(form => {
      form.addEventListener("submit", event => {
        if (!window.confirm("¿Eliminar esta tarea? Esta acción también eliminará su historial de sesiones.")) {
          event.preventDefault();
        }
      });
    });
  }

  async function initialize() {
    bindDeleteConfirmations();
    try {
      const data = await api("/api/productivity/profile");
      applyProfile(data.profile);
    } catch (error) {
      applyProfile(defaults);
      profileStatus.textContent = "No se pudieron cargar tus preferencias: " + error.message;
    }
    await Promise.all([loadSavedPlan(),loadInsights()]);
    generateButton.addEventListener("click",generatePlan);
    applyButton.addEventListener("click",acceptPlan);
    saveButton.addEventListener("click",saveProfile);
    resetButton.addEventListener("click",() => {
      applyProfile(defaults);
      profileStatus.textContent = "Valores iniciales restaurados. Guarda para conservarlos.";
    });
    horizon.addEventListener("change",() => { proposal = null; applyButton.disabled = true; });
  }

  initialize();
})();
