/* Placas — app web/mobile (PWA). JavaScript puro, sem build. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const brl = (cents) => (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const fmtDate = (iso) => iso ? new Date(iso.length === 10 ? iso + "T00:00:00" : iso + "Z").toLocaleDateString("pt-BR") : "—";
const fmtDateTime = (iso) => iso ? new Date(iso + "Z").toLocaleString("pt-BR") : "—";
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cleanPlate = (p) => (p || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const plateHtml = (display, small = false) => `<span class="plate${small ? " small" : ""}">${esc(display)}</span>`;
const TYPE_LABEL = { IPVA: "IPVA", LICENCIAMENTO: "Licenciamento", MULTA: "Multa", ESTACIONAMENTO: "Estacionamento", PEDAGIO: "Pedágio", OUTROS: "Outros" };

async function api(path, opts = {}) {
  const init = { headers: {}, ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.json);
  }
  const res = await fetch("/api" + path, init);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Erro ${res.status}`);
  return data;
}

let toastTimer;
function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3500);
}

function openModal(html) {
  $("#modal-body").innerHTML = html;
  const m = $("#modal");
  if (!m.open) m.showModal();
  return $("#modal-body");
}
const closeModal = () => $("#modal").close();

/* ------------------------------------------------------------- navegação */
let currentPlate = null;

function show(view, push = true) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  $$(".bottom-nav button").forEach((b) => b.classList.toggle("active", b.dataset.nav === view || (view === "vehicle" && b.dataset.nav === "vehicles")));
  if (view !== "scan") stopCamera();
  if (view === "vehicles") loadVehicles();
  if (view === "payments") loadPayments();
  if (view === "dashboard") loadDashboard();
  if (push) history.pushState({ view, plate: currentPlate }, "", view === "vehicle" ? `#veiculo/${currentPlate}` : `#${view}`);
  window.scrollTo(0, 0);
}

document.addEventListener("click", (e) => {
  const nav = e.target.closest("[data-nav]");
  if (nav) { e.preventDefault(); show(nav.dataset.nav); }
});

window.addEventListener("popstate", (e) => {
  const st = e.state || { view: "scan" };
  if (st.view === "vehicle" && st.plate) openVehicle(st.plate, false);
  else show(st.view, false);
});

/* ------------------------------------------------------------- câmera */
let stream = null;

async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    toast("Câmera ao vivo requer HTTPS. Use 'Foto / galeria'.", true);
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    const v = $("#video");
    v.srcObject = stream;
    await v.play();
    v.hidden = false;
    $("#preview").hidden = true;
    $("#camera-placeholder").hidden = true;
    $("#btn-capture").hidden = false;
    $("#btn-camera").textContent = "✕ Fechar câmera";
  } catch (err) {
    toast("Não foi possível abrir a câmera: " + err.message, true);
  }
}

function stopCamera() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  $("#video").hidden = true;
  $("#btn-capture").hidden = true;
  $("#btn-camera").textContent = "📷 Câmera ao vivo";
  if ($("#preview").hidden) $("#camera-placeholder").hidden = false;
}

$("#btn-camera").addEventListener("click", () => (stream ? stopCamera() : startCamera()));

$("#btn-capture").addEventListener("click", () => {
  const v = $("#video");
  const c = document.createElement("canvas");
  c.width = v.videoWidth;
  c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  stopCamera();
  c.toBlob((blob) => recognizeBlob(blob), "image/jpeg", 0.92);
});

$("#file-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (file) recognizeBlob(file);
  e.target.value = "";
});

/** Reduz a foto antes do upload (fotos de celular podem ter 12+ MP). */
async function downscale(blob, maxW = 1600) {
  try {
    const bmp = await createImageBitmap(blob);
    if (bmp.width <= maxW) return blob;
    const scale = maxW / bmp.width;
    const c = document.createElement("canvas");
    c.width = maxW;
    c.height = Math.round(bmp.height * scale);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise((r) => c.toBlob(r, "image/jpeg", 0.9));
  } catch {
    return blob;
  }
}

async function recognizeBlob(blob) {
  const prev = $("#preview");
  prev.src = URL.createObjectURL(blob);
  prev.hidden = false;
  $("#camera-placeholder").hidden = true;
  const out = $("#scan-result");
  out.innerHTML = `<div class="card"><span class="spinner"></span> Reconhecendo placa…</div>`;

  const fd = new FormData();
  fd.append("image", await downscale(blob), "foto.jpg");
  try {
    const data = await api("/recognize", { method: "POST", body: fd });
    renderRecognition(data);
  } catch (err) {
    out.innerHTML = `<div class="card">❌ ${esc(err.message)}</div>`;
  }
}

function renderRecognition({ recognition: r, vehicle, summary }) {
  const out = $("#scan-result");
  if (r.annotated_png_base64) $("#preview").src = "data:image/png;base64," + r.annotated_png_base64;
  if (!r.plate) {
    out.innerHTML = `<div class="card"><h2>Nenhuma placa identificada</h2>
      <p class="muted">Tente aproximar a câmera, evitar reflexos e enquadrar a placa de frente — ou digite a placa manualmente.</p>
      ${r.raw_text ? `<p class="muted small-text">Texto lido: ${esc(r.raw_text)}</p>` : ""}</div>`;
    return;
  }
  out.innerHTML = `<div class="card">
      <div class="result-head">
        ${plateHtml(r.display)}
        <div>
          <div><strong>${r.plate_type === "mercosul" ? "Padrão Mercosul" : "Padrão antigo"}</strong></div>
          <div class="muted small-text">Confiança ${Math.round(r.confidence * 100)}% · método: ${esc(r.source)}</div>
        </div>
      </div>
      ${r.crop_png_base64 ? `<img class="crop" alt="Recorte da placa" src="data:image/png;base64,${r.crop_png_base64}">` : ""}
      <form id="fix-form" class="inline-form">
        <input name="plate" value="${esc(r.plate)}" maxlength="8" aria-label="Corrigir placa">
        <button class="btn">Corrigir e consultar</button>
      </form>
    </div>
    <div id="scan-vehicle"></div>`;
  $("#fix-form").addEventListener("submit", (e) => {
    e.preventDefault();
    lookupPlate(e.target.plate.value);
  });
  renderScanVehicle(r.plate, vehicle, summary);
}

function renderScanVehicle(plate, vehicle, summary) {
  const box = $("#scan-vehicle");
  if (!vehicle) {
    box.innerHTML = `<div class="card"><h2>Veículo não cadastrado</h2>
      <p class="muted">A placa ${esc(plate)} não está na base.</p>
      <button class="btn primary" id="btn-register">Cadastrar veículo</button></div>`;
    $("#btn-register").onclick = () => vehicleForm({ plate });
    return;
  }
  box.innerHTML = `<div class="card">
      <div class="row" style="border:0;padding:0">
        <div class="grow"><strong>${esc(vehicle.model || "Veículo")}</strong> ${vehicle.color ? "· " + esc(vehicle.color) : ""}<br>
          <span class="muted small-text">${esc(vehicle.owner_name || "Proprietário não informado")}</span></div>
        <div class="right"><div class="muted small-text">${summary.count} débito(s) em aberto</div>
          <div style="font-size:1.3rem;font-weight:700">${brl(summary.total_cents)}</div></div>
      </div>
      <div class="actions"><button class="btn primary" id="btn-open-vehicle">Ver débitos e pagar</button></div>
    </div>`;
  $("#btn-open-vehicle").onclick = () => openVehicle(vehicle.plate);
}

async function lookupPlate(raw) {
  const plate = cleanPlate(raw);
  if (!/^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$/.test(plate)) return toast("Placa inválida. Use ABC1234 ou ABC1D23.", true);
  try {
    const data = await api(`/vehicles/${plate}`);
    if (!$("#scan-vehicle")) $("#scan-result").innerHTML = `<div id="scan-vehicle"></div>`;
    renderScanVehicle(plate, data.vehicle, data.summary);
  } catch {
    if (!$("#scan-vehicle")) $("#scan-result").innerHTML = `<div id="scan-vehicle"></div>`;
    renderScanVehicle(plate, null, null);
  }
}

$("#manual-form").addEventListener("submit", (e) => {
  e.preventDefault();
  $("#scan-result").innerHTML = "";
  lookupPlate($("#manual-plate").value);
});

/* ------------------------------------------------------------- veículos */
async function loadVehicles() {
  const q = $("#search-q").value.trim();
  const list = $("#vehicle-list");
  list.innerHTML = `<div class="card"><span class="spinner"></span></div>`;
  try {
    const vs = await api("/vehicles" + (q ? `?q=${encodeURIComponent(q)}` : ""));
    list.innerHTML = vs.length ? vs.map((v) => `
      <div class="row" data-plate="${esc(v.plate)}">
        ${plateHtml(v.display, true)}
        <div class="grow"><strong>${esc(v.model || "—")}</strong><br><span class="muted small-text">${esc(v.owner_name || "")}</span></div>
        <div class="right">${brl(v.total_cents)}<br>
          <span class="muted small-text">${v.open_debts} em aberto${v.overdue_count ? ` · <span class="badge late">${v.overdue_count} vencido(s)</span>` : ""}</span></div>
      </div>`).join("") : `<div class="card muted">Nenhum veículo encontrado.</div>`;
    $$("[data-plate]", list).forEach((r) => (r.onclick = () => openVehicle(r.dataset.plate)));
  } catch (err) {
    list.innerHTML = `<div class="card">❌ ${esc(err.message)}</div>`;
  }
}

$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); loadVehicles(); });
$("#btn-new-vehicle").addEventListener("click", () => vehicleForm({}));

function vehicleForm(v, editing = false) {
  const body = openModal(`<h2>${editing ? "Editar veículo" : "Cadastrar veículo"}</h2>
    <form id="vehicle-form">
      <label class="field">Placa<input name="plate" required maxlength="8" value="${esc(v.plate)}" ${editing ? "disabled" : ""}></label>
      <label class="field">Proprietário<input name="owner_name" value="${esc(v.owner_name)}"></label>
      <div class="grid-2">
        <label class="field">CPF/CNPJ<input name="owner_document" value="${esc(v.owner_document)}" inputmode="numeric"></label>
        <label class="field">Modelo<input name="model" value="${esc(v.model)}"></label>
        <label class="field">Cor<input name="color" value="${esc(v.color)}"></label>
        <label class="field">Ano<input name="year" type="number" min="1900" max="2100" value="${esc(v.year)}"></label>
      </div>
      <button class="btn primary">Salvar</button>
    </form>`);
  $("#vehicle-form", body).addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    try {
      const saved = editing
        ? await api(`/vehicles/${v.plate}`, { method: "PUT", json: data })
        : await api("/vehicles", { json: data });
      closeModal();
      toast("Veículo salvo");
      openVehicle(saved.plate);
    } catch (err) {
      toast(err.message, true);
    }
  });
}

/* ------------------------------------------------------------- detalhe / débitos */
async function openVehicle(plate, push = true) {
  currentPlate = cleanPlate(plate);
  show("vehicle", push);
  const box = $("#vehicle-detail");
  box.innerHTML = `<div class="card"><span class="spinner"></span></div>`;
  try {
    renderVehicle(await api(`/vehicles/${currentPlate}`));
  } catch (err) {
    box.innerHTML = `<div class="card">❌ ${esc(err.message)}</div>`;
  }
}

function breakdown(d) {
  const parts = [`Principal ${brl(d.principal_cents)}`];
  if (d.late_fee_cents) parts.push(`multa de mora ${brl(d.late_fee_cents)}`);
  if (d.interest_cents) parts.push(`juros ${brl(d.interest_cents)} (${d.months_late} ${d.months_late === 1 ? "mês" : "meses"})`);
  if (d.discount_cents) parts.push(`<span class="badge discount">desconto −${brl(d.discount_cents)}</span>`);
  return parts.join(" · ");
}

function renderVehicle({ vehicle: v, summary: s, history }) {
  const box = $("#vehicle-detail");
  box.innerHTML = `
    <div class="card">
      <div class="result-head">
        ${plateHtml(v.display)}
        <div class="grow">
          <strong>${esc(v.model || "Veículo")}</strong> ${v.year ? `(${v.year})` : ""} ${v.color ? "· " + esc(v.color) : ""}<br>
          <span class="muted">${esc(v.owner_name || "Proprietário não informado")} ${v.owner_document ? "· " + esc(v.owner_document) : ""}</span>
        </div>
      </div>
      <div class="actions">
        <button class="btn small" id="btn-edit">Editar</button>
        <button class="btn small" id="btn-add-debt">+ Lançar débito</button>
        <button class="btn small" id="btn-vehicle-payments">Pagamentos</button>
      </div>
    </div>

    <div class="stats">
      <div class="stat"><div class="label">Principal</div><div class="value">${brl(s.principal_cents)}</div></div>
      <div class="stat"><div class="label">Multa + juros</div><div class="value">${brl(s.late_fee_cents + s.interest_cents)}</div></div>
      <div class="stat"><div class="label">Descontos</div><div class="value">−${brl(s.discount_cents)}</div></div>
      <div class="stat"><div class="label">Total atualizado</div><div class="value">${brl(s.total_cents)}</div></div>
    </div>

    <h2>Débitos em aberto <span class="muted small-text">(calculado em ${fmtDate(s.ref_date)})</span></h2>
    <div class="card" id="debts">
      ${s.debts.length ? s.debts.map((d) => `
        <div class="debt-item">
          <input type="checkbox" value="${d.debt_id}" ${d.pending_payment_id ? "disabled" : "checked"} aria-label="Selecionar débito">
          <div><strong>${TYPE_LABEL[d.type] || d.type}</strong> — ${esc(d.description || "")}<br>
            <span class="muted small-text">Venc. ${fmtDate(d.due_date)}
              ${d.days_late ? `<span class="badge late">${d.days_late} dia(s) em atraso</span>` : ""}
              ${d.pending_payment_id ? `<span class="badge PENDENTE">pagamento #${d.pending_payment_id} pendente</span>` : ""}</span></div>
          <div class="num"><strong>${brl(d.total_cents)}</strong></div>
          <div class="breakdown">${breakdown(d)}
            ${d.pending_payment_id ? "" : `<button class="btn link small danger" data-cancel-debt="${d.debt_id}">cancelar</button>`}</div>
        </div>`).join("") : `<p class="muted">Nenhum débito em aberto. ✅</p>`}
      ${s.debts.length ? `<div class="actions" style="justify-content:space-between;align-items:center">
          <div>Selecionado: <strong id="sel-total">—</strong></div>
          <button class="btn primary" id="btn-pay">Pagar selecionados</button></div>` : ""}
    </div>

    ${history.length ? `<h2>Histórico</h2><div class="card table-wrap"><table>
      <tr><th>Débito</th><th>Venc.</th><th>Situação</th><th class="num">Valor pago</th></tr>
      ${history.map((d) => `<tr><td>${TYPE_LABEL[d.type] || d.type} — ${esc(d.description || "")}</td><td>${fmtDate(d.due_date)}</td>
        <td><span class="badge ${d.status}">${d.status}</span></td><td class="num">${d.paid_amount_cents ? brl(d.paid_amount_cents) : "—"}</td></tr>`).join("")}
    </table></div>` : ""}`;

  const updateSel = () => {
    const ids = selectedDebts();
    const total = s.debts.filter((d) => ids.includes(d.debt_id)).reduce((a, d) => a + d.total_cents, 0);
    if ($("#sel-total")) $("#sel-total").textContent = brl(total);
    if ($("#btn-pay")) $("#btn-pay").disabled = !ids.length;
  };
  $$("#debts input[type=checkbox]").forEach((c) => c.addEventListener("change", updateSel));
  updateSel();

  $("#btn-edit").onclick = () => vehicleForm(v, true);
  $("#btn-add-debt").onclick = () => debtForm(v.plate);
  $("#btn-vehicle-payments").onclick = () => showVehiclePayments(v.plate);
  if ($("#btn-pay")) $("#btn-pay").onclick = () => checkout(v.plate, selectedDebts());
  $$("[data-cancel-debt]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Cancelar este débito?")) return;
    try { await api(`/debts/${b.dataset.cancelDebt}`, { method: "DELETE" }); toast("Débito cancelado"); openVehicle(v.plate, false); }
    catch (err) { toast(err.message, true); }
  }));
}

const selectedDebts = () => $$("#debts input[type=checkbox]:checked").map((c) => Number(c.value));

function debtForm(plate) {
  const today = new Date().toISOString().slice(0, 10);
  const body = openModal(`<h2>Lançar débito</h2>
    <form id="debt-form">
      <label class="field">Tipo<select name="type">${Object.entries(TYPE_LABEL).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
      <label class="field">Descrição<input name="description" placeholder="ex.: IPVA 2026, infração art. 218"></label>
      <div class="grid-2">
        <label class="field">Valor (R$)<input name="amount" required inputmode="decimal" placeholder="0,00"></label>
        <label class="field">Vencimento<input name="due_date" type="date" required value="${today}"></label>
      </div>
      <button class="btn primary">Lançar</button>
    </form>`);
  $("#debt-form", body).addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/vehicles/${plate}/debts`, { json: Object.fromEntries(new FormData(e.target)) });
      closeModal();
      toast("Débito lançado");
      openVehicle(plate, false);
    } catch (err) {
      toast(err.message, true);
    }
  });
}

/* ------------------------------------------------------------- checkout */
async function checkout(plate, debtIds) {
  const body = openModal(`<span class="spinner"></span> Calculando opções…`);
  let sim;
  try {
    sim = await api(`/vehicles/${plate}/payments/simulate`, { json: { debt_ids: debtIds } });
  } catch (err) {
    body.innerHTML = `❌ ${esc(err.message)}`;
    return;
  }
  const methods = await api("/payment-methods");
  const byMethod = {};
  sim.options.forEach((o) => (byMethod[o.method] ||= []).push(o));

  body.innerHTML = `<h2>Forma de pagamento</h2>
    <p>Débitos atualizados: <strong>${brl(sim.debts_total_cents)}</strong></p>
    <form id="pay-form">
      ${methods.map((m, i) => {
        const opts = byMethod[m.id] || [];
        const first = opts[0];
        return `<label class="method">
          <input type="radio" name="method" value="${m.id}" ${i === 0 ? "checked" : ""}>
          <strong>${esc(m.label)}</strong> — <span data-total="${m.id}">${brl(first.total_cents)}</span><br>
          <span class="muted small-text">${esc(m.description)}</span>
          ${opts.length > 1 ? `<select name="inst-${m.id}" data-method="${m.id}">
            ${opts.map((o) => `<option value="${o.installments}">${o.installments}x de ${brl(o.installment_cents)}${o.interest_cents ? ` (total ${brl(o.total_cents)})` : " sem juros"}</option>`).join("")}
          </select>` : ""}
        </label>`;
      }).join("")}
      <label class="field">Nome do pagador (opcional)<input name="payer_name"></label>
      <button class="btn primary" style="width:100%">Confirmar pagamento</button>
    </form>`;

  $$("select[data-method]", body).forEach((sel) => sel.addEventListener("change", () => {
    const o = byMethod[sel.dataset.method].find((x) => x.installments === Number(sel.value));
    $(`[data-total="${sel.dataset.method}"]`, body).textContent = brl(o.total_cents);
  }));

  $("#pay-form", body).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const method = f.get("method");
    const btn = $("button.primary", e.target);
    btn.disabled = true;
    try {
      const p = await api(`/vehicles/${plate}/payments`, {
        json: { debt_ids: sim.debt_ids, method, installments: Number(f.get(`inst-${method}`) || 1), payer_name: f.get("payer_name") },
      });
      showPayment(p);
      openVehicle(plate, false);
    } catch (err) {
      toast(err.message, true);
      btn.disabled = false;
    }
  });
}

function paymentDetailHtml(p) {
  return `<h2>Pagamento #${p.id} <span class="badge ${p.status}">${p.status}</span></h2>
    <p>${esc(p.method_label)} · ref. <code>${esc(p.reference)}</code> · placa ${esc(p.plate)}</p>
    <div class="table-wrap"><table>
      <tr><th>Débito</th><th class="num">Total</th></tr>
      ${p.items.map((i) => `<tr><td>${TYPE_LABEL[i.type] || i.type} — ${esc(i.description || "")}<br>
        <span class="muted small-text">principal ${brl(i.principal_cents)}${i.late_fee_cents + i.interest_cents ? ` · encargos ${brl(i.late_fee_cents + i.interest_cents)}` : ""}${i.discount_cents ? ` · desconto −${brl(i.discount_cents)}` : ""}</span></td>
        <td class="num">${brl(i.total_cents)}</td></tr>`).join("")}
      <tr><td>Subtotal débitos</td><td class="num">${brl(p.debts_total_cents)}</td></tr>
      ${p.fee_cents ? `<tr><td>Tarifa</td><td class="num">${brl(p.fee_cents)}</td></tr>` : ""}
      ${p.interest_cents ? `<tr><td>Juros do parcelamento</td><td class="num">${brl(p.interest_cents)}</td></tr>` : ""}
      <tr class="total-row"><td>Total ${p.installments > 1 ? `(${p.installments}x de ${brl(p.installment_cents)})` : ""}</td><td class="num">${brl(p.total_cents)}</td></tr>
    </table></div>
    ${p.pix_payload && p.status === "PENDENTE" ? `<h2>PIX copia e cola</h2><div id="pix-qr"></div>
      <div class="pix-code">${esc(p.pix_payload)}</div>
      <div class="actions"><button class="btn small" id="btn-copy-pix">Copiar código</button></div>` : ""}
    ${p.method === "BOLETO" && p.status === "PENDENTE" ? `<p>Código de referência do boleto: <code>${esc(p.reference)}</code></p>` : ""}
    ${p.expires_at && p.status === "PENDENTE" ? `<p class="muted small-text">Expira em ${fmtDateTime(p.expires_at)}</p>` : ""}
    ${p.confirmed_at ? `<p class="muted small-text">Confirmado em ${fmtDateTime(p.confirmed_at)}</p>` : ""}
    <div class="actions">
      ${p.status === "PENDENTE" ? `<button class="btn ok" data-act="confirm">✔ Confirmar recebimento</button>
        <button class="btn danger" data-act="cancel">Cancelar</button>` : ""}
      ${p.status === "APROVADO" ? `<button class="btn danger" data-act="refund">Estornar</button>` : ""}
    </div>`;
}

function showPayment(p) {
  const body = openModal(paymentDetailHtml(p));
  if (p.pix_payload && p.status === "PENDENTE") {
    if (window.QRCode) new QRCode($("#pix-qr", body), { text: p.pix_payload, width: 200, height: 200 });
    else $("#pix-qr", body).remove();
    $("#btn-copy-pix", body).onclick = () => navigator.clipboard?.writeText(p.pix_payload).then(() => toast("Código PIX copiado"));
  }
  $$("[data-act]", body).forEach((b) => (b.onclick = async () => {
    const labels = { confirm: "Confirmar o recebimento deste pagamento?", cancel: "Cancelar este pagamento?", refund: "Estornar este pagamento? Os débitos voltarão a ficar em aberto." };
    if (!confirm(labels[b.dataset.act])) return;
    try {
      const upd = await api(`/payments/${p.id}/${b.dataset.act}`, { method: "POST" });
      toast(`Pagamento ${upd.status.toLowerCase()}`);
      showPayment(upd);
      refreshCurrent();
    } catch (err) {
      toast(err.message, true);
    }
  }));
}

function refreshCurrent() {
  const active = $(".view.active").id.replace("view-", "");
  if (active === "vehicle" && currentPlate) openVehicle(currentPlate, false);
  if (active === "payments") loadPayments();
}

/* ------------------------------------------------------------- pagamentos */
let paymentFilter = "";

function paymentRow(p) {
  return `<div class="row" data-payment="${p.id}">
    <div class="grow"><strong>#${p.id} · ${esc(p.method_label)}</strong> ${p.installments > 1 ? `(${p.installments}x)` : ""}<br>
      <span class="muted small-text">${esc(p.plate)} · ${fmtDateTime(p.created_at)}</span></div>
    <div class="right">${brl(p.total_cents)}<br><span class="badge ${p.status}">${p.status}</span></div>
  </div>`;
}

async function loadPayments() {
  const list = $("#payment-list");
  list.innerHTML = `<div class="card"><span class="spinner"></span></div>`;
  try {
    const ps = await api("/payments" + (paymentFilter ? `?status=${paymentFilter}` : ""));
    list.innerHTML = ps.length ? ps.map(paymentRow).join("") : `<div class="card muted">Nenhum pagamento.</div>`;
    bindPaymentRows(list, ps);
  } catch (err) {
    list.innerHTML = `<div class="card">❌ ${esc(err.message)}</div>`;
  }
}

function bindPaymentRows(el, ps) {
  $$("[data-payment]", el).forEach((r) => (r.onclick = () => showPayment(ps.find((p) => p.id === Number(r.dataset.payment)))));
}

async function showVehiclePayments(plate) {
  const ps = await api(`/payments?plate=${plate}`);
  const body = openModal(`<h2>Pagamentos de ${esc(plate)}</h2><div class="list">${ps.length ? ps.map(paymentRow).join("") : `<p class="muted">Nenhum pagamento.</p>`}</div>`);
  bindPaymentRows(body, ps);
}

$("#payment-filters").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  $$(".chip", e.currentTarget).forEach((c) => c.classList.toggle("active", c === chip));
  paymentFilter = chip.dataset.status;
  loadPayments();
});

/* ------------------------------------------------------------- painel */
async function loadDashboard() {
  try {
    const [s, methods, recs] = await Promise.all([api("/stats"), api("/payment-methods"), api("/recognitions")]);
    const label = Object.fromEntries(methods.map((m) => [m.id, m.label]));
    $("#stats").innerHTML = [
      ["Veículos", s.vehicles], ["Débitos em aberto", s.open_debts], ["Vencidos", s.overdue_debts],
      ["Principal em aberto", brl(s.open_principal_cents)], ["Pagamentos pendentes", s.pending_payments],
      ["Total recebido", brl(s.received_cents)], ["Leituras de placa", s.recognitions],
    ].map(([l, v]) => `<div class="stat"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("")
      + Object.entries(s.received_by_method).map(([m, v]) => `<div class="stat"><div class="label">Recebido · ${esc(label[m] || m)}</div><div class="value">${brl(v)}</div></div>`).join("");
    $("#methods").innerHTML = methods.map((m) => `<div class="row" style="cursor:default"><div class="grow"><strong>${esc(m.label)}</strong><br>
      <span class="muted small-text">${esc(m.description)}</span></div>
      <div class="right small-text">${m.instant_approval ? "Aprovação imediata" : "Aguarda confirmação"}<br>até ${m.max_installments}x</div></div>`).join("");
    $("#recognitions").innerHTML = recs.length ? recs.map((r) => `<div class="row" ${r.plate ? `data-plate="${esc(r.plate)}"` : ""}>
      <div class="grow">${r.plate ? plateHtml(r.plate, true) : `<span class="muted">sem placa</span>`}</div>
      <div class="right small-text">${Math.round((r.confidence || 0) * 100)}%<br>${fmtDateTime(r.created_at)}</div></div>`).join("")
      : `<div class="card muted">Nenhuma leitura ainda.</div>`;
    $$("#recognitions [data-plate]").forEach((r) => (r.onclick = () => openVehicle(r.dataset.plate)));
  } catch (err) {
    toast(err.message, true);
  }
}

/* ------------------------------------------------------------- init */
(async function init() {
  try {
    const h = await api("/health");
    const pill = $("#ocr-status");
    pill.textContent = h.ocr_available ? "OCR ativo" : "OCR indisponível";
    pill.title = h.ocr_available ? "Tesseract encontrado" : "Instale o Tesseract no servidor";
  } catch {
    $("#ocr-status").textContent = "offline";
  }
  const hash = location.hash.slice(1);
  if (hash.startsWith("veiculo/")) openVehicle(hash.split("/")[1], false);
  else if (["vehicles", "payments", "dashboard"].includes(hash)) show(hash, false);
  history.replaceState({ view: hash.startsWith("veiculo/") ? "vehicle" : hash || "scan", plate: currentPlate }, "");

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
