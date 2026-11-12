// Formulário de RDO: linhas dinâmicas, captura de localização e rascunho local.
(function () {
  var form = document.getElementById("form-rdo");
  if (!form) return;
  var CHAVE = "diario-rascunho-" + form.getAttribute("data-obra");

  // ---------- linhas dinâmicas
  form.addEventListener("click", function (e) {
    var add = e.target.closest("[data-adicionar]");
    if (add) {
      var tpl = document.getElementById(add.getAttribute("data-adicionar"));
      add.closest("fieldset").querySelector("[data-destino]").appendChild(tpl.content.cloneNode(true));
      return;
    }
    var rem = e.target.closest("[data-remover]");
    if (rem) { rem.closest("[data-linha]").remove(); salvarRascunho(); }
  });

  // ---------- localização
  var elStatus = document.getElementById("loc_status"), elTexto = document.getElementById("loc-texto");
  function definirLoc(status, lat, lon, prec, texto, classe) {
    elStatus.value = status;
    document.getElementById("lat").value = lat === null ? "" : lat;
    document.getElementById("lon").value = lon === null ? "" : lon;
    document.getElementById("precisao").value = prec === null ? "" : prec;
    elTexto.textContent = texto;
    elTexto.className = "badge " + classe;
  }
  function capturar() {
    elTexto.textContent = "Obtendo…"; elTexto.className = "badge";
    if (!navigator.geolocation) {
      definirLoc("indisponivel", null, null, null, "Indisponível neste navegador", "badge-aviso"); return;
    }
    navigator.geolocation.getCurrentPosition(function (p) {
      definirLoc("ok", p.coords.latitude.toFixed(7), p.coords.longitude.toFixed(7), Math.round(p.coords.accuracy),
        "Registrada (± " + Math.round(p.coords.accuracy) + " m)", "badge-ok");
    }, function (err) {
      if (err.code === 1) definirLoc("negada", null, null, null, "Permissão negada (use HTTPS e permita a localização)", "badge-aviso");
      else if (err.code === 3) definirLoc("timeout", null, null, null, "Tempo esgotado", "badge-aviso");
      else definirLoc("indisponivel", null, null, null, "Indisponível", "badge-aviso");
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  }
  document.getElementById("loc-retry").addEventListener("click", capturar);
  capturar();

  form.addEventListener("submit", function (e) {
    if (elStatus.value !== "ok" &&
        !window.confirm("A localização não foi registrada e isso ficará marcado no registro. Salvar mesmo assim?")) {
      e.preventDefault(); return;
    }
    // o rascunho só é apagado depois que o servidor confirma o registro (ver app.js)
  });

  // ---------- rascunho local (protege contra perda de sinal ou aba fechada)
  var temporizador = null;
  function coletar() {
    var dados = { campos: {}, linhas: {} };
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.type === "file" || el.type === "hidden" || el.type === "password" || el.name === "_csrf") return;
      if (el.type === "checkbox") { if (el.checked) (dados.campos[el.name] = dados.campos[el.name] || []).push(el.value); return; }
      (dados.campos[el.name] = dados.campos[el.name] || []).push(el.value);
    });
    form.querySelectorAll("fieldset[data-grupo]").forEach(function (fs) {
      if (fs.getAttribute("data-grupo") !== "foto") dados.linhas[fs.getAttribute("data-grupo")] = fs.querySelectorAll("[data-linha]").length;
    });
    return dados;
  }
  function salvarRascunho() {
    clearTimeout(temporizador);
    temporizador = setTimeout(function () {
      try { localStorage.setItem(CHAVE, JSON.stringify(coletar())); } catch (_) {}
    }, 400);
  }
  function restaurar(d) {
    var tpls = { serv: "tpl-serv", eq: "tpl-eq", oc: "tpl-oc" };
    Object.keys(d.linhas || {}).forEach(function (g) {
      var fs = form.querySelector('fieldset[data-grupo="' + g + '"]'), dest = fs.querySelector("[data-destino]");
      while (dest.querySelectorAll("[data-linha]").length < d.linhas[g]) dest.appendChild(document.getElementById(tpls[g]).content.cloneNode(true));
      while (dest.querySelectorAll("[data-linha]").length > d.linhas[g]) dest.lastElementChild.remove();
    });
    var cont = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || !(el.name in d.campos) || el.type === "file" || el.type === "hidden") return;
      if (el.type === "checkbox") { el.checked = d.campos[el.name].indexOf(el.value) !== -1; return; }
      var i = cont[el.name] = (cont[el.name] || 0);
      if (i < d.campos[el.name].length) el.value = d.campos[el.name][i];
      cont[el.name] = i + 1;
    });
  }
  form.addEventListener("input", salvarRascunho);
  form.addEventListener("change", salvarRascunho);
  try {
    var salvo = localStorage.getItem(CHAVE);
    if (salvo) {
      var aviso = document.getElementById("aviso-rascunho"); aviso.hidden = false;
      document.getElementById("rascunho-restaurar").addEventListener("click", function () { restaurar(JSON.parse(salvo)); aviso.hidden = true; });
      document.getElementById("rascunho-descartar").addEventListener("click", function () { localStorage.removeItem(CHAVE); aviso.hidden = true; });
    }
  } catch (_) {}
})();
