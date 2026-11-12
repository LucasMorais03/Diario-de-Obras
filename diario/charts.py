"""Gráficos SVG gerados no servidor (sem bibliotecas externas)."""
from markupsafe import Markup, escape

W, H = 640, 230
ML, MR, MT, MB = 40, 12, 14, 44


def _vazio(msg="Sem dados no período."):
    return Markup(f'<svg viewBox="0 0 {W} 80" class="grafico" role="img"><text x="{W/2}" y="44" class="g-rotulo" text-anchor="middle">{escape(msg)}</text></svg>')


def _rotulos_x(pontos, xs, base_y):
    passo = max(1, -(-len(pontos) // 8))  # no máximo ~8 rótulos no eixo
    out = []
    for i, (rot, _v) in enumerate(pontos):
        if i % passo == 0:
            out.append(f'<text x="{xs[i]:.1f}" y="{base_y + 16}" class="g-rotulo" text-anchor="middle">{escape(rot)}</text>')
    return "".join(out)


def _grade(vmax, base_y, topo_y, unidade=""):
    out = []
    for k in range(5):
        v = vmax * k / 4
        y = base_y - (base_y - topo_y) * k / 4
        out.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{W - MR}" y2="{y:.1f}" class="g-grade"/>'
                   f'<text x="{ML - 6}" y="{y + 4:.1f}" class="g-rotulo" text-anchor="end">{v:g}{unidade}</text>')
    return "".join(out)


def linha_svg(pontos, vmax=100, meta=None, titulo="Gráfico de linha"):
    """pontos: lista de (rótulo, valor|None)."""
    validos = [p for p in pontos if p[1] is not None]
    if not validos:
        return _vazio()
    base_y, topo_y = H - MB, MT
    n = len(pontos)
    xs = [ML + (W - ML - MR) * (i + 0.5) / n for i in range(n)]
    ys = [None if v is None else base_y - (base_y - topo_y) * min(v, vmax) / vmax for _r, v in pontos]
    partes = [_grade(vmax, base_y, topo_y, "%")]
    if meta is not None:
        ym = base_y - (base_y - topo_y) * meta / vmax
        partes.append(f'<line x1="{ML}" y1="{ym:.1f}" x2="{W - MR}" y2="{ym:.1f}" class="g-meta"/>'
                      f'<text x="{W - MR}" y="{ym - 4:.1f}" class="g-rotulo" text-anchor="end">meta {meta:g}%</text>')
    trecho = [(x, y) for x, y in zip(xs, ys) if y is not None]
    partes.append('<polyline class="g-linha" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in trecho) + '"/>')
    for (x, y), (rot, v) in zip(((x, y) for x, y in zip(xs, ys) if y is not None), validos):
        partes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" class="{"g-ponto-baixo" if meta is not None and v < meta else "g-ponto"}">'
                      f'<title>{escape(rot)}: {v:.0f}%</title></circle>')
    partes.append(_rotulos_x(pontos, xs, base_y))
    return Markup(f'<svg viewBox="0 0 {W} {H}" class="grafico" role="img" aria-label="{escape(titulo)}">{"".join(partes)}</svg>')


def barras_svg(pontos, unidade="", titulo="Gráfico de barras", classe="g-barra", destaque=None):
    """pontos: lista de (rótulo, valor); destaque: função(valor)->bool para realçar barras."""
    if not pontos or all(v is None for _r, v in pontos):
        return _vazio()
    maximo = max(v or 0 for _r, v in pontos)
    vmax = float(max(4, -(-int(maximo * 1.05 + 0.999) // 4) * 4))  # múltiplo de 4: marcas inteiras no eixo
    base_y, topo_y = H - MB, MT
    n = len(pontos)
    larg = (W - ML - MR) / n
    xs = [ML + larg * (i + 0.5) for i in range(n)]
    partes = [_grade(vmax, base_y, topo_y, unidade)]
    for x, (rot, v) in zip(xs, pontos):
        v = v or 0
        h = (base_y - topo_y) * v / vmax
        cl = "g-barra-alerta" if destaque and destaque(v) else classe
        partes.append(f'<rect x="{x - larg * 0.35:.1f}" y="{base_y - h:.1f}" width="{larg * 0.7:.1f}" height="{h:.1f}" class="{cl}">'
                      f'<title>{escape(rot)}: {v:g}{unidade}</title></rect>')
    partes.append(_rotulos_x(pontos, xs, base_y))
    return Markup(f'<svg viewBox="0 0 {W} {H}" class="grafico" role="img" aria-label="{escape(titulo)}">{"".join(partes)}</svg>')
