// Comportamentos globais, sem scripts inline (compatível com a política de segurança de conteúdo).
document.addEventListener("click", function (e) {
  if (e.target.closest("[data-imprimir]")) window.print();
});
(function () {
  var id = document.body.getAttribute("data-limpar-rascunho");
  if (id) { try { localStorage.removeItem("diario-rascunho-" + id); } catch (_) {} }
})();
