"use strict";
/* Legado Verde · cliente web: KPIs, actividad en tiempo real (SSE), asistente por texto y voz, modo coche. */

const $ = (s) => document.querySelector(s);
const mxn = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 });
const mxn2 = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
const num = new Intl.NumberFormat("es-MX");

const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
const leer = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };

const estado = {
  periodo: "mes",
  token: leer("lv_token") || "",
  sesion: leer("lv_sesion") || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)),
  pendiente: null,
  enCoche: false,
};
guardar("lv_sesion", estado.sesion);

/* ---------------------------------------------------------------- red */
async function api(ruta, opciones = {}) {
  const headers = { ...(opciones.headers || {}) };
  if (estado.token) headers.Authorization = `Bearer ${estado.token}`;
  if (opciones.json) { headers["Content-Type"] = "application/json"; opciones.body = JSON.stringify(opciones.json); }
  const r = await fetch(ruta, { ...opciones, headers });
  if (r.status === 401) { pedirToken(); throw new Error("Necesitas iniciar sesión."); }
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.detail || `Error ${r.status}`);
  return datos;
}

function pedirToken() {
  const dlg = $("#dlgToken");
  if (dlg.open) return;
  dlg.showModal();
}
$("#formToken").addEventListener("submit", () => {
  estado.token = $("#token").value.trim();
  guardar("lv_token", estado.token);
  iniciar();
});

function aviso(texto) {
  const el = $("#aviso");
  el.textContent = texto; el.hidden = false;
  clearTimeout(aviso.t); aviso.t = setTimeout(() => (el.hidden = true), 3500);
}

/* ---------------------------------------------------------------- KPIs */
async function cargarKpis() {
  const { resumen, equilibrio } = await api(`/api/kpis?periodo=${estado.periodo}`);
  $("#kVentas").textContent = mxn.format(resumen.ventas_producto);
  $("#kVentasSub").textContent = `${resumen.num_ventas} ventas · ${resumen.periodo}`;
  $("#kSobres").textContent = num.format(resumen.sobres);
  $("#kSobresSub").textContent = resumen.ticket_promedio ? `ticket promedio ${mxn.format(resumen.ticket_promedio)}` : " ";
  $("#kContrib").textContent = mxn.format(resumen.contribucion);
  $("#kContrib").className = Number(resumen.contribucion) < 0 ? "neg" : "";
  $("#kContribTipo").textContent = resumen.tipo_contribucion;
  $("#kContribTipo").className = "etiqueta" + (resumen.tipo_contribucion === "estimado" ? " etiqueta--est" : "");

  const avance = Math.max(0, Math.min(100, Number(equilibrio.avance_pct || 0)));
  $("#kPE").textContent = `${Math.round(Number(equilibrio.avance_pct || 0))}%`;
  $("#peBarra").style.width = `${avance}%`;
  $("#pePista").setAttribute("aria-valuenow", String(Math.round(avance)));
  $("#kPESub").textContent = equilibrio.meta_sobres
    ? `faltan ${mxn.format(equilibrio.faltante)} · meta ≈ ${num.format(equilibrio.meta_sobres)} sobres`
    : `faltan ${mxn.format(equilibrio.faltante)} de contribución`;

  pintarCanales(resumen);
}

function pintarCanales(resumen) {
  const cont = $("#canales");
  const filas = resumen.por_canal || [];
  if (!filas.length) { cont.innerHTML = '<p class="vacio">Sin ventas en el periodo.</p>'; $("#canalesNota").textContent = ""; return; }
  const max = Math.max(...filas.map((f) => Number(f.total_producto)), 1);
  cont.replaceChildren(...filas.map((f) => {
    const div = document.createElement("div");
    div.className = "canal";
    const cps = f.contribucion_por_sobre === null ? null : Number(f.contribucion_por_sobre);
    div.innerHTML = `
      <div class="canal__nom"></div>
      <div class="canal__pista"><i style="width:${(Number(f.total_producto) / max) * 100}%"></i></div>
      <div class="canal__num"></div>`;
    div.querySelector(".canal__nom").innerHTML = `${esc(f.canal)}<small>${num.format(f.sobres)} sobres${f.pendientes_conciliar ? ` · ${f.pendientes_conciliar} por conciliar` : ""}</small>`;
    div.querySelector(".canal__num").innerHTML = `${mxn.format(f.total_producto)}<small class="${cps !== null && cps < 0 ? "neg" : "pos"}">${cps === null ? "—" : mxn2.format(cps)} / sobre</small>`;
    return div;
  }));
  $("#canalesNota").textContent = resumen.pendientes_conciliar ? "contribución por sobre · hay cargos por conciliar" : "contribución por sobre";
}

/* ---------------------------------------------------------------- actividad */
async function cargarFeed() {
  const ventas = await api("/api/ventas?limite=15");
  const feed = $("#feed");
  if (!ventas.length) return;
  feed.replaceChildren(...ventas.map((v) => itemVenta(v)));
}

function itemVenta(v, nuevo = false) {
  const li = document.createElement("li");
  li.className = "item" + (nuevo ? " nuevo" : "") + (v.estado === "anulada" ? " anulada" : "");
  li.dataset.id = v.id;
  const quien = v.cliente ? ` · ${esc(v.cliente)}` : "";
  li.innerHTML = `
    <span class="origen ${v.origen === "voz" ? "origen--voz" : ""}">${esc(etiquetaOrigen(v.origen))}</span>
    <span class="desc">${num.format(v.cantidad)} sobres · ${esc(v.canal)}${quien}<br><small>${v.fecha || v.mes_reportado || "sin fecha"}${v.pendiente_conciliar ? " · por conciliar" : ""}</small></span>
    <span class="monto">${mxn.format(v.total_producto)}</span>`;
  return li;
}
const etiquetaOrigen = (o) => ({ mercadolibre: "ML", amazon: "AMZ", voz: "voz", texto: "texto", manual: "manual", importacion: "hist" }[o] || o);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------------------------------------------------------- tiempo real */
let fuente;
function conectarEventos() {
  fuente?.close();
  fuente = new EventSource(`/api/eventos?token=${encodeURIComponent(estado.token)}`);
  const vivo = $("#vivo");
  fuente.addEventListener("hola", () => { vivo.classList.add("ok"); vivo.lastElementChild.textContent = "En vivo"; });
  fuente.addEventListener("venta", (e) => {
    const v = JSON.parse(e.data);
    const feed = $("#feed");
    feed.querySelector(".vacio")?.remove();
    const previo = feed.querySelector(`[data-id="${v.id}"]`);
    const li = itemVenta(v, true);
    previo ? previo.replaceWith(li) : feed.prepend(li);
    while (feed.children.length > 15) feed.lastElementChild.remove();
    refrescarPronto();
  });
  fuente.addEventListener("sync", (e) => aviso("Sincronización: " + Object.entries(JSON.parse(e.data)).map(([k, v]) => `${k} ${v}`).join(" · ")));
  fuente.onerror = () => { vivo.classList.remove("ok"); vivo.lastElementChild.textContent = "Reconectando"; };
}
let temporizador;
function refrescarPronto() { clearTimeout(temporizador); temporizador = setTimeout(() => cargarKpis().catch(() => {}), 400); }

/* ---------------------------------------------------------------- asistente */
async function preguntar(texto, modo) {
  texto = texto.trim();
  if (!texto) return null;
  const r = await api("/api/asistente", { method: "POST", json: { sesion_id: estado.sesion, texto, modo } });
  estado.pendiente = r.pendiente;
  if (r.refrescar) refrescarPronto();
  return r;
}

$("#formComando").addEventListener("submit", async (e) => {
  e.preventDefault();
  const entrada = $("#entrada");
  const texto = entrada.value;
  entrada.value = "";
  await enviarTexto(texto);
});

async function enviarTexto(texto) {
  const caja = $("#respuesta");
  caja.hidden = false;
  $("#respuestaTexto").textContent = "Pensando…";
  try {
    const r = await preguntar(texto, "texto");
    if (!r) { caja.hidden = true; return; }
    $("#respuestaTexto").textContent = r.texto;
    $("#pendienteAcciones").hidden = !r.pendiente;
  } catch (err) {
    $("#respuestaTexto").textContent = err.message;
  }
}
document.querySelectorAll("#pendienteAcciones [data-decir]").forEach((b) => b.addEventListener("click", () => enviarTexto(b.dataset.decir)));

/* ---------------------------------------------------------------- voz */
const Reconocedor = window.SpeechRecognition || window.webkitSpeechRecognition;

/** Escucha una frase. Usa Web Speech API; si no existe, graba y transcribe en el servidor (Whisper). */
function escucharFrase(alParcial) {
  if (Reconocedor) {
    return new Promise((resolve, reject) => {
      const rec = new Reconocedor();
      rec.lang = "es-MX"; rec.interimResults = true; rec.maxAlternatives = 1; rec.continuous = false;
      let final = "";
      rec.onresult = (ev) => {
        let parcial = "";
        for (const res of ev.results) (res.isFinal ? (final += res[0].transcript) : (parcial += res[0].transcript));
        alParcial?.(final || parcial);
      };
      rec.onerror = (ev) => (ev.error === "no-speech" ? resolve("") : reject(new Error("Micrófono: " + ev.error)));
      rec.onend = () => resolve(final.trim());
      rec.start();
    });
  }
  return grabarYTranscribir(alParcial);
}

async function grabarYTranscribir(alParcial) {
  const flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const tipo = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg"].find((t) => window.MediaRecorder?.isTypeSupported?.(t)) || "";
  const grabador = new MediaRecorder(flujo, tipo ? { mimeType: tipo } : undefined);
  const partes = [];
  grabador.ondataavailable = (e) => e.data.size && partes.push(e.data);
  const terminado = new Promise((r) => (grabador.onstop = r));
  grabador.start();
  alParcial?.("Grabando… toca de nuevo para terminar");
  estado.detenerGrabacion = () => grabador.state === "recording" && grabador.stop();
  setTimeout(estado.detenerGrabacion, 9000); // máximo 9 s por frase
  await terminado;
  flujo.getTracks().forEach((t) => t.stop());
  estado.detenerGrabacion = null;
  const blob = new Blob(partes, { type: grabador.mimeType || "audio/webm" });
  const form = new FormData();
  form.append("audio", blob, "frase." + (blob.type.includes("mp4") ? "m4a" : "webm"));
  const { texto } = await api("/api/voz/transcribir", { method: "POST", body: form });
  return texto;
}

function hablar(texto) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(texto);
    u.lang = "es-MX"; u.rate = 1.04;
    const voz = speechSynthesis.getVoices().find((v) => v.lang === "es-MX") || speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
    if (voz) u.voice = voz;
    u.onend = resolve; u.onerror = resolve;
    speechSynthesis.speak(u);
  });
}

$("#micTexto").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  if (estado.detenerGrabacion) return estado.detenerGrabacion();
  b.classList.add("activo");
  try {
    const texto = await escucharFrase((t) => ($("#entrada").value = t));
    if (texto) await enviarTexto(texto);
  } catch (err) { aviso(err.message); } finally { b.classList.remove("activo"); $("#entrada").value = ""; }
});

/* ---------------------------------------------------------------- modo coche */
let candado = null;
const coche = $("#coche");
function fijarEstadoCoche(nombre, texto) { coche.dataset.estado = nombre; $("#cocheEstado").textContent = texto; }

$("#abrirCoche").addEventListener("click", async () => {
  coche.hidden = false; estado.enCoche = true;
  fijarEstadoCoche("listo", "Toca para hablar");
  try { candado = await navigator.wakeLock?.request("screen"); } catch (_) { candado = null; }
});
$("#cerrarCoche").addEventListener("click", () => {
  coche.hidden = true; estado.enCoche = false;
  speechSynthesis?.cancel(); candado?.release?.(); candado = null;
});
$("#cocheMic").addEventListener("click", () => (estado.detenerGrabacion ? estado.detenerGrabacion() : cicloCoche()));
document.querySelectorAll("#cocheConf [data-decir]").forEach((b) => b.addEventListener("click", () => cicloCoche(b.dataset.decir)));

/** Un ciclo: escuchar → preguntar → hablar. Si queda una confirmación pendiente, vuelve a escuchar solo. */
async function cicloCoche(textoDirecto) {
  if (coche.dataset.estado === "escuchando" || coche.dataset.estado === "pensando") return;
  try {
    let texto = textoDirecto;
    if (!texto) {
      fijarEstadoCoche("escuchando", "Escuchando…");
      texto = await escucharFrase((t) => ($("#cocheOido").textContent = t));
    }
    if (!texto) { fijarEstadoCoche("listo", "No te escuché · toca para hablar"); return; }
    $("#cocheOido").textContent = `“${texto}”`;
    fijarEstadoCoche("pensando", "Pensando…");
    const r = await preguntar(texto, "voz");
    $("#cocheResp").textContent = r.texto;
    $("#cocheConf").hidden = !r.pendiente;
    fijarEstadoCoche("hablando", "Respondiendo");
    await hablar(r.texto);
    if (r.pendiente && estado.enCoche) {
      fijarEstadoCoche("listo", "¿Confirmas?");
      setTimeout(() => estado.enCoche && cicloCoche(), 250); // escucha la confirmación sin tocar la pantalla
    } else {
      fijarEstadoCoche("listo", "Toca para hablar");
    }
  } catch (err) {
    fijarEstadoCoche("listo", "Toca para reintentar");
    $("#cocheResp").textContent = err.message;
    hablar(err.message);
  }
}
document.addEventListener("visibilitychange", async () => {
  if (estado.enCoche && document.visibilityState === "visible" && !candado) {
    try { candado = await navigator.wakeLock?.request("screen"); } catch (_) {}
  }
});

/* ---------------------------------------------------------------- periodo e inicio */
document.querySelectorAll(".segmento button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".segmento button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  estado.periodo = b.dataset.periodo;
  cargarKpis().catch((e) => aviso(e.message));
}));

async function iniciar() {
  try {
    await Promise.all([cargarKpis(), cargarFeed()]);
    conectarEventos();
  } catch (e) { aviso(e.message); }
}
iniciar();
