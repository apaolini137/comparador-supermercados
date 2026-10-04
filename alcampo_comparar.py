"""
Compara un pedido tuyo de Carrefour con los precios de Alcampo (compraonline.alcampo.es), SIN iniciar sesión en ninguna.

Cómo funciona (3 pasos, ver el mensaje que acompaña a este fichero):
  1) python alcampo_comparar.py consultas
        Lee tu historial de pedidos de Carrefour y escribe alcampo_exportar_listo.js (el script ya trae las búsquedas dentro).
  2) En Chrome, en compraonline.alcampo.es (con tu código postal puesto), F12 -> Consola: pegar el contenido de ese fichero.
        Hace las búsquedas desde TU navegador (Alcampo protege su web con un WAF) y descarga alcampo_resultados.json.
  3) python alcampo_comparar.py comparar
        Empareja cada producto, calcula cuánto costaría el pedido en Alcampo y muestra el informe.

Solo lee precios públicos. No necesita instalar nada: Python 3.8 o superior.
El emparejamiento de productos es el mismo motor que usa el MCP de Carrefour (mismo tipo, atributos, estado, uso).
"""

import argparse
import json
import re
import statistics
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

VERSION = "1.18"


# ================================================================ motor de emparejamiento (copiado del MCP de Carrefour)

_RE_A_PESO = re.compile(r"a granel|aprox|al peso|peso variable|por kg|\bkg\b.*aprox", re.I)


_STOP = {"el", "la", "los", "las", "de", "del", "en", "y", "a", "al", "o", "e", "un", "una", "para", "con", "aprox", "ud", "uds",
         "pack", "carrefour", "mercado"}


_UNIDADES = {"g", "kg", "gr", "ml", "l", "cl", "lt", "mg", "unidades"}


_GAMAS = {"classic", "extra", "sensation", "essential"}


def _sin_acentos(t):
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    # sinónimos de grafía entre Carrefour y Alcampo
    return re.sub(r"\bcubos?\b|\bcubitos\b", "dados", re.sub(r"biscotte", "biscote", t))


def _palabras(nombre, quitar_gamas=False):
    """Palabras significativas de un nombre de producto (sin tamaños, marca blanca ni conectores), con sus acentos."""
    out = []
    for w in re.findall(r"[a-záéíóúüñ]+", str(nombre or "").lower()):
        n = _sin_acentos(w)
        if n in _STOP or n in _UNIDADES or len(n) < 2 or (quitar_gamas and n in _GAMAS):
            continue
        out.append(w)
    return out


_ATRIBUTOS = {"spray", "congelado", "congelada", "congelados", "congeladas", "fresco", "fresca", "frescos", "frescas",
              "ecologico", "ecologica", "bio", "lactosa", "gluten", "vegano", "vegana", "integral", "zero", "light"}


_FORMATOS = {"botella", "garrafa", "lata", "brik", "bolsa", "tarro", "frasco", "sobre", "tubo", "bandeja", "caja", "tableta"}


def _raiz(w):
    n = _sin_acentos(w)
    return n[:-1] if len(n) > 3 and n.endswith("s") else n


_SINON_ATTR = {"ligero": "light", "bio": "ecologico", "ecologica": "ecologico", "vegana": "vegano", "congelada": "congelado",
               "fresca": "fresco"}


_ETIQ_ATTR = {"gluten": "sin gluten (una mezcla sin gluten se comporta distinto)", "lactosa": "sin lactosa", "ecologico": "ecológico",
              "vegano": "vegano", "integral": "integral", "zero": "zero", "light": "light"}


_ATTR_R = {_raiz(x) for x in _ATRIBUTOS}


# calificadores que no pueden perderse en un equivalente estricto ('de oliva' no es 'vegetal'; 'doble rollo' no es un rollo normal)
_CALIF_R = {_raiz(x) for x in ("oliva", "virgen", "girasol", "desnatada", "semidesnatada", "entera", "doble", "triple", "compact", "gas")}


# ingredientes/coberturas que convierten un producto en otro ('tortita de arroz' != 'tortita con chocolate')
_EXTRAS_R = {_raiz(x) for x in ("chocolate", "cacao", "caramelo", "yogur", "coco", "miel", "campero", "camperas", "gourmet")}


# palabras de forma que pueden ir delante del tipo ('Hojas de espinaca' = espinacas)
_FORMA_R = {_raiz(x) for x in ("hojas", "porciones", "trozos", "cubos", "rodajas", "filetes", "lonchas", "laminas", "brotes", "tiras", "mitades")}


_FORM_R = {_raiz(x) for x in _FORMATOS}


_GEN_R = {_raiz(x) for x in ("especial", "tradicional", "clasico", "original", "suave", "fino", "premium", "calidad",
                             "selecta", "seleccion", "mini", "maxi", "nuevo", "gran", "grande",
                             # formas de corte: dados, rodajas o troceado es el mismo producto para quien compra
                             "dados", "rodajas", "troceado", "troceada", "trozos", "cortado", "cortada", "laminas", "tiras", "mitades")}


_USOS_R = [{_raiz(x) for x in g} for g in (
    ("bizcocho", "reposteria", "pasteleria", "tarta", "magdalena", "bollo"),
    ("pizza", "panaderia", "levadura", "masa", "madre", "pan"),
    ("tempura", "rebozar", "rebozado", "fritura", "freir"))]


_ESTADOS_R = {"fresco": {_raiz(x) for x in ("fresco", "fresca", "frescos", "frescas")},
              "congelado": {_raiz(x) for x in ("congelado", "congelada", "congelados", "congeladas")},
              "conserva": {_raiz(x) for x in ("lata", "conserva", "tarro", "bote", "frasco")}}


def _tamano(nombre):
    """Tamaño en g o ml de un nombre ('285 g', '1 l', '3x140 g', '1,5 kg'), o None."""
    t = str(nombre or "").lower().replace(",", ".")
    m = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(kg|gr|g|ml|cl|lt|l)\b", t) or \
        re.search(r"(\d+)\s*(?:latas|botellas|briks|unidades|uds?\.?|bolsitas|sobres|tarros|frascos)\s*(?:de\s*)?(\d+(?:\.\d+)?)\s*(kg|gr|g|ml|cl|lt|l)\b", t)
    if m:
        mult, cant, uni = int(m.group(1)), float(m.group(2)), m.group(3)
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|gr|g|ml|cl|lt|l)\b", t)
        if not m:
            return None
        mult, cant, uni = 1, float(m.group(1)), m.group(2)
    return mult * cant * {"kg": 1000, "g": 1, "gr": 1, "l": 1000, "lt": 1000, "ml": 1, "cl": 10}[uni]


def _texto_tamano(nombre):
    """El tamaño tal como aparece en el nombre ('400 ml', '3x140 g'), para poder mostrarlo."""
    m = re.search(r"\d+\s*x\s*\d+(?:[.,]\d+)?\s*(?:kg|gr|g|ml|cl|lt|l)\b|\d+(?:[.,]\d+)?\s*(?:kg|gr|g|ml|cl|lt|l)\b", str(nombre or ""), re.I)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


_RE_SABOR = re.compile(r"sabor(?:\s+a)?\s+([a-záéíóúüñ]+)|(aromatizad[oa]s?)|(?:con|al)\s+(?:sabor|aroma)", re.I)


def _sabor(nombre):
    """Si el nombre indica sabor o aroma añadido ('sabor ajo', 'aromatizado'), devuelve una descripción; si no, None."""
    m = _RE_SABOR.search(str(nombre or ""))
    if not m:
        return None
    return f"sabor {m.group(1)}" if m.group(1) else "aromatizado"


_SINONIMOS_USO = [("repostería", "pastelería"), ("panadería", "pizza"), ("rebozar", "tempura")]


def _perfil(nombre, marca="", venta=None):
    """Qué es un producto: su tipo (primera palabra: 'maíz', 'harina', 'aceite'), el resto de palabras, atributos que
    no pueden cambiar (spray, congelado, sin lactosa...), formato y tamaño."""
    raices = [_SINON_ATTR.get(r, r) for r in (_raiz(w) for w in _palabras(nombre, quitar_gamas=True))]
    de_marca = {_raiz(w) for w in re.findall(r"[a-záéíóúüñ]+", str(marca or "").lower())}
    def grupo(r):                                   # "bizcocho" y "repostería" son el mismo uso: se comparan como grupo
        for i, g in enumerate(_USOS_R):
            if r in g:
                return f"uso{i}"
        return r
    resto_total = {grupo(r) for r in raices[1:] if r not in _GEN_R}
    todas = set(raices)
    estado = next((nom for nom, g in _ESTADOS_R.items() if todas & g), None)
    cabeza = next((r for r in raices if r not in _GEN_R), raices[0] if raices else None)
    sin_gen = [r for r in raices if r not in _GEN_R]
    return {"head": cabeza, "ini": sin_gen[:3], "resto_total": resto_total, "resto": resto_total - de_marca,
            "attrs": {r for r in raices if r in _ATTR_R}, "formatos": {r for r in raices if r in _FORM_R},
            "usos": {i for i, g in enumerate(_USOS_R) if todas & g},
            "estado": estado,
            # ¿el original es un producto fresco? (lo dice el nombre, se vende a peso o es "a granel / aprox")
            "fresco_probable": estado == "fresco" or venta not in (None, "units") or bool(_RE_A_PESO.search(str(nombre or ""))),
            "tamano": _tamano(nombre)}


def _parecido(o, c, estricto):
    """0 si no es una alternativa válida; si lo es, su parecido (0-1). Estricto: mismo tipo, mismos atributos, mismo
    estado (fresco / congelado / conserva) y uso, formato compatible, tamaño entre la mitad y el doble y la mitad de las
    palabras significativas del original. Laxo: tamaño entre un tercio y el triple y una cuarta parte de las palabras."""
    if not o["head"]:
        return 0.0
    if c["head"] != o["head"]:
        ini = c.get("ini") or []                    # "Hojas de espinaca" sí es espinacas; "harina de maíz" no es "maíz dulce"
        if o["head"] not in ini or not all(r in _FORMA_R for r in ini[:ini.index(o["head"])]):
            return 0.0
    if estricto and ((o["resto_total"] & _CALIF_R) - c["resto_total"] - {c["head"]}):
        return 0.0                                  # aceite de oliva -> vegetal, doble rollo -> rollo normal: solo "menos exacto"
    if estricto and ((c["resto_total"] & _EXTRAS_R) - o["resto_total"] - {o["head"]}):
        return 0.0                                  # el candidato lleva chocolate/yogur... y el original no
    if not o["attrs"] <= c["attrs"]:
        return 0.0                                  # un spray no se sustituye por una botella; congelado por fresco, tampoco
    if o["formatos"] and c["formatos"] and not (o["formatos"] & c["formatos"]):
        return 0.0
    if c["estado"] == "fresco" and not o["fresco_probable"]:
        return 0.0                                  # el original no es un fresco (maíz dulce de conserva): el maíz fresco no lo sustituye
    if o["estado"] and c["estado"] and o["estado"] != c["estado"]:
        return 0.0                                  # maíz en lata y maíz fresco (o congelado) no son equivalentes
    if o["usos"]:
        if not (o["usos"] & c["usos"]):
            return 0.0                              # harina para bizcochos != harina de pizza / panadería
    elif c["usos"] and estricto:
        return 0.0                                  # el original no tiene un uso concreto y el candidato sí: solo "menos exacto"
    if not o["estado"] and c["estado"] == "congelado" and estricto:
        return 0.0                                  # el candidato dice ser congelado y el original no: solo "menos exacto"
    if o["tamano"] and c["tamano"]:
        lo, hi = (0.5, 2.0) if estricto else (1 / 3, 3.0)
        if not lo <= c["tamano"] / o["tamano"] <= hi:
            return 0.0                              # 1 l o 5 l no sustituyen a 200 ml
    sim = len(o["resto"] & (c["resto_total"] | {c["head"]})) / len(o["resto"]) if o["resto"] else 1.0
    if sim < (0.5 if estricto else 0.25):
        return 0.0
    return max(sim, 0.01)


def _consultas_alternativas(nombre, marca=""):
    """Textos de búsqueda de más a menos específicos. Siempre llevan el tipo de producto y las palabras que no pueden
    cambiar (spray, congelado, lata, bizcochos...), y no llevan la marca ni palabras vacías como 'especial'."""
    de_marca = {_raiz(w) for w in re.findall(r"[a-záéíóúüñ]+", str(marca or "").lower())}
    todas = _palabras(nombre, quitar_gamas=True)
    palabras = [w for w in todas if _raiz(w) not in _GEN_R and _raiz(w) not in de_marca] or todas
    if not palabras:
        return []
    usos = set().union(*_USOS_R)
    esenciales = [i for i, w in enumerate(palabras) if i == 0 or _raiz(w) in _ATTR_R or _raiz(w) in _FORM_R
                  or _raiz(w) in usos or any(_raiz(w) in g for g in _ESTADOS_R.values())]
    qs = []
    for k in (3, 2, 1):
        idx = set(esenciales[:k])
        for i in range(len(palabras)):
            if len(idx) >= k:
                break
            idx.add(i)
        q = " ".join(palabras[i] for i in sorted(idx))
        if q and q not in qs:
            qs.append(q)
    # Mismo uso con otras palabras: una harina "para bizcochos" también se anuncia como de "repostería".
    raices = {_raiz(w) for w in palabras}
    sinonimos = []
    for i, g in enumerate(_USOS_R):
        if raices & g:
            sinonimos += [f"{palabras[0]} {s}" for s in _SINONIMOS_USO[i] if _raiz(s) not in raices]
    return qs[:1] + [q for q in sinonimos if q not in qs] + qs[1:]


# ================================================================ Alcampo: lectura de resultados

_UNIDADES_G_ML = {"kg": 1000, "g": 1, "gr": 1, "l": 1000, "lt": 1000, "ml": 1, "cl": 10}


def tamano_envase(envase):
    """'6000ml' -> 6000.0 (ml); '500g' -> 500.0 (g); '40 por envase' -> None."""
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*(kg|gr|g|lt|l|ml|cl)\s*$", str(envase or ""), re.I)
    return float(m.group(1).replace(",", ".")) * _UNIDADES_G_ML[m.group(2).lower()] if m else None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def normalizar_producto(p):
    """Un producto de la API de búsqueda de Alcampo -> el formato que guarda alcampo_resultados.json (igual que el JS)."""
    up = p.get("unitPrice") or {}
    return {"sku": p.get("retailerProductId"), "nombre": p.get("name") or "", "marca": p.get("brand") or "",
            "envase": p.get("packSizeDescription") or "", "precio": _f((p.get("price") or {}).get("amount")),
            "unidad": up.get("unitName"), "precio_unidad": _f((up.get("price") or {}).get("amount")),
            "disponible": bool(p.get("available")),
            "promos": [{"tipo": x.get("type"), "descripcion": x.get("description"), "cantidad_requerida": x.get("requiredProductQuantity")}
                       for x in (p.get("promotions") or [])],
            "categoria": " > ".join(p.get("categoryPath") or [])}


def parsear_busqueda(j, maximo=30):
    """Respuesta de /api/webproductpagews/v6/product-pages/search -> lista de productos normalizados, en orden de relevancia."""
    vistos, out = set(), []
    for g in j.get("productGroups") or []:
        for p in g.get("decoratedProducts") or []:
            if p.get("productId") in vistos:
                continue
            vistos.add(p.get("productId"))
            out.append(normalizar_producto(p))
    return out[:maximo]


# ================================================================ Carrefour: historial y consultas

_REEMBOLSO = re.compile(r"reembols|cancel|anulad|devuelt|rechazad|fallid", re.I)


def _rutas_historial():
    h = Path.home()
    return [Path.cwd() / "historial_pedidos.json", h / "Downloads" / "MCP_Carrefour" / "historial_pedidos.json",
            h / "Downloads" / "historial_pedidos.json"]


def cargar_historial(ruta=None):
    for r in ([Path(ruta)] if ruta else _rutas_historial()):
        if r.is_file():
            return json.loads(r.read_text(encoding="utf-8")), r
    raise SystemExit("No encuentro historial_pedidos.json (el del MCP de Carrefour). Indica la ruta con --historial.")


def elegir_pedido(h, id_pedido=None, minimo_lineas=20):
    det = h.get("detalle") or {}
    if id_pedido:
        if str(id_pedido) not in det:
            raise SystemExit(f"El pedido {id_pedido} no está en el historial.")
        return det[str(id_pedido)]
    for p in h.get("pedidos") or []:                       # del más reciente al más antiguo
        d = det.get(str(p.get("id")))
        if d and len(d.get("lineas") or []) >= minimo_lineas and not _REEMBOLSO.search(f"{d.get('estado') or ''} {d.get('cobro') or ''}"):
            return d
    raise SystemExit("No hay ningún pedido con detalle suficiente en el historial. Indica uno con --pedido.")


def es_a_peso(linea):
    return linea.get("venta") not in (None, "units") or bool(_RE_A_PESO.search(str(linea.get("nombre") or "")))


def consultas_de_linea(nombre):
    """Qué buscar en Alcampo para un producto: la consulta específica y el tipo de producto a secas (para no perder candidatos)."""
    qs = _consultas_alternativas(nombre, "")
    return list(dict.fromkeys(qs[:1] + qs[-1:])) if qs else []


_NO_MARCA = {"variedad", "cubos", "dados", "vainas", "polvo", "carrefour", "extra", "classic", "sensation", "mercado", "pack", "mini", "light", "zero", "natural", "especial"}


def consultas_extra(nombre):
    """Búsquedas cortas de rescate para una línea sin equivalente: la primera palabra, cada palabra con mayúscula que pueda ser
    marca ('Aperol', 'Babybel') y las dos primeras palabras significativas. Se usan SOLO cuando las normales no encontraron nada."""
    toks = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", str(nombre or ""))
    base = set(consultas_de_linea(nombre))
    qs = []
    if toks and len(toks[0]) >= 4:
        qs.append(toks[0].lower())
    qs += [t.lower() for t in toks[1:] if t[0].isupper() and len(t) >= 4 and t.lower() not in _NO_MARCA]
    sig = _palabras(nombre, quitar_gamas=True)
    if len(sig) >= 2:
        qs.append(" ".join(sig[:2]))
    qs.append(re.sub(r"(?i)\bcubos?\b", "dados", " ".join(sig[:2])))      # 'cebolla cubos' -> 'cebolla dados' (así lo llama Alcampo)
    return [q for q in dict.fromkeys(qs) if q not in base][:4]


def consultas_del_pedido(pedido):
    vistas = []
    for l in pedido.get("lineas") or []:
        if es_a_peso(l):
            continue
        vistas += consultas_de_linea(l["nombre"])
    return list(dict.fromkeys(vistas))


# ================================================================ emparejamiento y coste

def limpiar_nombre_alcampo(nombre):
    """Los nombres de Alcampo empiezan por la marca en mayúsculas ('AUCHAN Queso rallado...', 'PRODUCTO ALCAMPO Alcaparras...').
    Se quita ese prefijo para que el tipo de producto sea la primera palabra real; se conservan los atributos ('ECOLÓGICO', 'BIO')."""
    toks, i = str(nombre or "").split(), 0
    while i < len(toks) - 1 and any(ch.isalpha() for ch in toks[i]) and toks[i] == toks[i].upper():
        i += 1
    return " ".join(toks[i:] + [t for t in toks[:i] if _raiz(re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", t)) in _ATTR_R])


_RE_UDS = re.compile(r"(\d+)\s*(?:unidades|uds?|rollos|huevos|compresas|bolsitas|sobres|pastillas|latas|botellas|briks|porciones|lonchas|"
                     r"capsulas|tiritas|servilletas|panuelos|bolsas|toallitas|salvaslips|tampones|pa[nñ]ales|por envase)\b", re.I)


def unidades(texto):
    """Nº de unidades de un pack ('12 rollos', '40 por envase', 'docena', 'pack de 6', '6 x 1 l'), o None."""
    t = _sin_acentos(texto).replace(",", ".")
    if re.search(r"\bdocena\b", t):
        return 12.0
    if re.search(r"media docena", t):
        return 6.0
    m = _RE_UDS.search(t) or re.search(r"pack\s*(?:de\s*)?(\d+)\b", t) or re.search(r"\b(\d+)\s*x\s*\d+(?:\.\d+)?\s*(?:kg|gr|g|ml|cl|lt|l)\b", t)
    return float(m.group(1)) if m else None


def _marca_en_nombre(marca, nombre):
    mt = [_raiz(w) for w in re.findall(r"[a-záéíóúüñ]+", _sin_acentos(marca).lower()) if len(w) > 1]
    nt = {_raiz(w) for w in re.findall(r"[a-záéíóúüñ]+", _sin_acentos(nombre).lower())}
    return bool(mt) and all(m in nt for m in mt)


_RE_2A = re.compile(r"2[ªaº]?\.?\s*(?:unidad|und|ud\.?)\s*(?:al\s*)?-?\s*(\d+)\s*%", re.I)


_RE_NXM = re.compile(r"(?<![\d,.])([2-6])\s*x\s*([1-5])(?![\d,.]|\s*(?:g|kg|ml|l|cl)\b)", re.I)


def ahorro_promo(promos, precio, q):
    """Ahorro de una promoción por cantidad para q unidades a 'precio'. Entiende '2ª unidad -50 %' / '2ª ud. al 70 %'
    ('al 70 %' = 70 % de descuento, como se usa en los súper) y 'NxM' (3x2, 2x1).
    Devuelve (ahorro, descripción) o (0.0, None)."""
    for p in promos or []:
        d = str(p.get("descripcion") or "")
        if re.search(r"club|tarjeta|acum", d, re.I):
            continue                                   # descuento de cliente acumulado en tarjeta: no es precio de estantería
        m = _RE_2A.search(d)
        if m and q >= 2:
            return round((q // 2) * precio * int(m.group(1)) / 100, 2), d
        m = _RE_NXM.search(d)
        if m:
            n, pagas = int(m.group(1)), int(m.group(2))
            if pagas < n and q >= n:
                return round((q // n) * (n - pagas) * precio, 2), d
    return 0.0, None


def emparejar(linea, productos, n=None):
    """Elige en Alcampo el equivalente de una línea de Carrefour. Devuelve None si no hay ninguno. Con n, devuelve una lista
    con los n mejores candidatos (para que el usuario elija en 'confirmar').
    El tamaño NO descarta (un pack de 6 briks sí se compara con un brik, por precio por unidad); solo se avisa y se ajusta."""
    o = _perfil(linea["nombre"], "", linea.get("venta"))
    tam_o = o["tamano"]
    o_sin = dict(o, tamano=None)
    # marcas probables del original: palabras con mayúscula inicial que no son la primera ('Aperol', 'Babybel', 'Vulpi')
    marcas_o = {_raiz(t.lower()) for t in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", linea["nombre"])
                if t[0].isupper() and len(t) >= 4 and t.lower() not in _NO_MARCA}
    mejores = []
    for c in productos:
        if not c.get("disponible") or not c.get("precio"):
            continue
        pc = _perfil(limpiar_nombre_alcampo(c["nombre"]), c.get("marca", ""))
        tam_c = tamano_envase(c.get("envase")) or pc["tamano"]
        pc = dict(pc, tamano=None)
        marcas_c = {_raiz(w) for w in re.findall(r"[a-záéíóúüñ]+", str(c.get("marca") or "").lower())}
        if o["head"] in marcas_c:
            pc = dict(pc, head=o["head"])                  # la marca va de cabeza en el original ('Fanta de naranja...') y en Alcampo es 'FANTA ... Refresco'
        sim = _parecido(o_sin, pc, True)
        nivel = "estricta" if sim else ("laxa" if _parecido(o_sin, pc, False) else None)
        solo = ""
        if not nivel and marcas_o & marcas_c:
            nivel, solo = "laxa", " - solo coincide la marca"   # 'Licor aperitivo Aperol' / 'APEROL Licor...'
        if not nivel:
            n_o0, n_c0 = unidades(linea["nombre"]), unidades(f"{c['nombre']} {c.get('envase') or ''}")
            b_o0, b_c0 = (tam_o, tam_c) if tam_o and tam_c else ((n_o0, n_c0) if n_o0 and n_c0 else (None, None))
            ini = pc.get("ini") or []
            mismo_tipo = bool(o["head"]) and (pc["head"] == o["head"] or (o["head"] in ini and all(r in _FORMA_R for r in ini[:ini.index(o["head"])])))
            sin_calif = not ((o["resto_total"] & _CALIF_R) - pc["resto_total"] - {pc["head"]})      # no perder 'semidesnatada', 'oliva', 'doble'...
            if (mismo_tipo and sin_calif and len(o["resto"]) <= 3 and b_o0 and b_c0 and 0.5 <= b_c0 / b_o0 <= 2.0
                    and not (o["attrs"] - pc["attrs"])):
                nivel, solo = "laxa", " - solo coincide tipo y tamaño"
        if not nivel:
            continue
        completo = sim >= 0.999                                        # el candidato contiene todas las palabras del original (misma gama)
        n_o, n_c = unidades(linea["nombre"]), unidades(f"{c['nombre']} {c.get('envase') or ''}")
        base_o, base_c, medida = (tam_o, tam_c, "tamaño") if tam_o and tam_c else ((n_o, n_c, "unidades") if n_o and n_c else (None, None, None))
        ratio = base_c / base_o if base_o and base_c else None
        comparable = ratio is not None and 0.8 <= ratio <= 1.25
        # fuera de 0,5x-2x el precio por unidad no es fiable, salvo que sea un múltiplo exacto (6 x 1 l frente a 1 l: mismo envase en multipack)
        en_rango = ratio is not None and (0.5 <= ratio <= 2.0 or any(m >= 2 and abs(f - m) <= 0.03 * m for f in (ratio, 1 / ratio) for m in [round(f)]))
        misma_marca = _marca_en_nombre(c.get("marca", ""), linea["nombre"])
        por_original = c["precio"] / ratio if ratio else c["precio"]  # lo que costaría un envase del tamaño del original
        mejores.append(((nivel != "estricta", not misma_marca, not en_rango, not completo, por_original), c, nivel, misma_marca, comparable, en_rango, base_o, base_c, medida, solo))
    if not mejores:
        return None if n is None else []
    orden = sorted(mejores, key=lambda x: x[0])
    if n is None:
        return _construir(linea, orden[0])
    return [_construir(linea, m) for m in orden[:n]]


def _construir(linea, m):
    """Del candidato elegido al resultado: coste ajustado al tamaño, formato y promoción."""
    _, c, nivel, misma_marca, comparable, en_rango, base_o, base_c, medida, solo = m
    q, precio = linea["cantidad"], c["precio"]
    if base_o and base_c:
        coste = round(precio * (q * base_o) / base_c, 2)               # siempre al precio por unidad: 1,5 l no cuesta lo que 1,25 l
        if comparable:
            formato = "mismo formato"
        else:
            formato = (f"ajustado por tamaño ({c['envase']} frente a {_texto_tamano(linea['nombre']) or 'el original'})" if medida == "tamaño"
                       else f"ajustado por unidades ({base_c:g} frente a {base_o:g})")
        if not en_rango:
            formato += " - tamaño muy distinto"
    else:
        coste, formato = round(precio * q, 2), "tamaño sin comprobar"
    formato += solo
    ahorro, texto_promo = ahorro_promo(c.get("promos"), precio, q) if comparable else (0.0, None)
    return {"alcampo": c, "nivel": nivel, "misma_marca": misma_marca, "formato": formato, "coste": coste, "en_rango": en_rango,
            "coste_con_promo": round(coste - ahorro, 2), "promo_aplicada": texto_promo}


def valor_lista(linea):
    """Lo que vale una línea de Carrefour a precio de lista (sin descuentos). En las de peso, la cantidad no son unidades:
    se usa el importe sin descuento que guarda el historial."""
    if es_a_peso(linea):
        for k in ("importe_sin_dto", "importe"):
            if linea.get(k) is not None:
                return round(float(linea[k]), 2)
    pu = linea.get("precio_lista") or linea.get("precio_pagado") or 0
    return round(pu * (linea.get("cantidad") or 0), 2)


def pool_de_linea(linea, resultados):
    """Productos de Alcampo encontrados por las búsquedas de esta línea (sin repetir)."""
    pool, vistos = [], set()
    for q in consultas_de_linea(linea["nombre"]) + consultas_extra(linea["nombre"]):
        for c in resultados.get(q) or []:
            if c.get("sku") not in vistos:
                vistos.add(c.get("sku"))
                pool.append(c)
    return pool


def cargar_decisiones(ruta):
    r = Path(ruta)
    return json.loads(r.read_text(encoding="utf-8")) if r.is_file() else {}


def guardar_decisiones(ruta, dec):
    Path(ruta).write_text(json.dumps(dec, ensure_ascii=False, indent=1), encoding="utf-8")


def comparar_pedido(pedido, resultados, decisiones=None):
    """resultados: {consulta: [productos de Alcampo]}. decisiones: lo que el usuario confirmó o rechazó en 'confirmar'.
    Devuelve el detalle por línea y los totales."""
    filas, revisar, a_peso, sin_eq = [], [], [], []
    for l in pedido.get("lineas") or []:
        if es_a_peso(l):
            a_peso.append({"nombre": l["nombre"], "carrefour_lista": valor_lista(l)})
            continue
        pool = pool_de_linea(l, resultados)
        lista = valor_lista(l)
        d = (decisiones or {}).get(l["nombre"]) or {}
        if d.get("decision") == "no":                                  # tú dijiste que ninguno vale
            sin_eq.append({"nombre": l["nombre"], "cantidad": l["cantidad"], "carrefour_lista": lista, "carrefour_pagado": l.get("importe"), "descartado": True})
            continue
        e = None
        if d.get("decision") == "si":                                  # tú elegiste este candidato
            e = next((x for x in emparejar(l, pool, n=50) if x["alcampo"].get("sku") == d.get("sku")), None)
            if e:
                e = dict(e, en_rango=True, confirmado=True, formato=e["formato"] + " - confirmado por ti")
                filas.append({"nombre": l["nombre"], "cantidad": l["cantidad"], "carrefour_lista": lista, "carrefour_pagado": l.get("importe") or 0.0, **e})
                continue
        e = emparejar(l, pool)
        if e is None:
            sin_eq.append({"nombre": l["nombre"], "cantidad": l["cantidad"], "carrefour_lista": lista, "carrefour_pagado": l.get("importe")})
            continue
        fila = {"nombre": l["nombre"], "cantidad": l["cantidad"], "carrefour_lista": lista, "carrefour_pagado": l.get("importe") or 0.0, **e}
        # fiable = equivalencia estricta y formato comprobado; lo demás se lista aparte y no cuenta en los totales
        (filas if e["nivel"] == "estricta" and e["en_rango"] else revisar).append(fila)
    t_lista = round(sum(f["carrefour_lista"] for f in filas), 2)
    t_pag = round(sum(f["carrefour_pagado"] for f in filas), 2)
    t_alc = round(sum(f["coste"] for f in filas), 2)
    t_alc_p = round(sum(f["coste_con_promo"] for f in filas), 2)
    v_sin = round(sum(s["carrefour_lista"] for s in sin_eq) + sum(f["carrefour_lista"] for f in revisar), 2)
    v_peso = round(sum(x["carrefour_lista"] for x in a_peso), 2)
    cobertura = t_lista / (t_lista + v_sin) if (t_lista + v_sin) else 0.0
    return {"filas": filas, "a_revisar": revisar, "sin_equivalente": sin_eq, "a_peso": a_peso,
            "totales": {"emparejado_carrefour_lista": t_lista, "emparejado_carrefour_pagado": t_pag, "emparejado_alcampo": t_alc,
                        "emparejado_alcampo_con_promo": t_alc_p, "sin_equivalente_carrefour_lista": v_sin,
                        "a_peso_carrefour_lista": v_peso, "cobertura_valor": round(cobertura, 3),
                        # misma base en los dos lados: todo el pedido; lo que no se compara cuenta a precio de Carrefour
                        "cesta_completa_carrefour_lista": round(t_lista + v_sin + v_peso, 2),
                        "estimacion_cesta_completa_alcampo": round(t_alc_p + v_sin + v_peso, 2)}}


# ================================================================ informe

def _eur(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _texto_promos(f):
    """Promociones del producto de Alcampo elegido, y si se han aplicado al coste, para poder comprobarlo a ojo."""
    ps = [str(x.get("descripcion") or "") for x in f["alcampo"].get("promos") or [] if x.get("descripcion")]
    if not ps:
        return ""
    return "\n     promos de Alcampo: " + " | ".join(x[:55] for x in ps[:3]) + (f"  -> APLICADA: {f['promo_aplicada']}" if f.get("promo_aplicada") else " (ninguna aplicada)")


def informe(pedido, r, destino=None, fecha_precios=None, envio_alcampo=None):
    t, n_fil, n_sin, n_peso = r["totales"], len(r["filas"]), len(r["sin_equivalente"]) + len(r["a_revisar"]), len(r["a_peso"])
    tt = pedido.get("totales") or {}
    out = [f"Pedido de Carrefour {pedido.get('id')} ({str(pedido.get('fecha_pedido') or '')[:10]}): {len(pedido.get('lineas') or [])} líneas, "
           f"pagaste {_eur(tt.get('total_final') or 0)} (envío {_eur(tt.get('envio_pagado') or 0)}; cheque ahorro {_eur(tt.get('cheque_ahorro_usado') or 0)}).",
           f"Alcampo: precios{' del ' + fecha_precios if fecha_precios else ''}{' · zona: ' + destino if destino else ''}.",
           "", f"Emparejado: {n_fil} de {n_fil + n_sin} líneas comparables ({t['cobertura_valor'] * 100:.0f} % del valor). "
           f"{n_peso} a peso (no comparables) y {n_sin} sin equivalente fiable ({len(r['a_revisar'])} de ellas a revisar abajo)."
           + (f" {sum(1 for f in r['filas'] if f.get('confirmado'))} confirmadas por ti." if any(f.get('confirmado') for f in r['filas']) else ""), "",
           "Sobre lo emparejado:",
           f"  Carrefour, precio de lista:  {_eur(t['emparejado_carrefour_lista'])}   (lo que pagaste, con promos: {_eur(t['emparejado_carrefour_pagado'])})",
           f"  Alcampo, estantería:         {_eur(t['emparejado_alcampo'])}   ({_pct(t['emparejado_alcampo'], t['emparejado_carrefour_lista'])})"]
    if t["emparejado_alcampo_con_promo"] != t["emparejado_alcampo"]:
        out.append(f"  Alcampo, con 2ª unidad:      {_eur(t['emparejado_alcampo_con_promo'])}   ({_pct(t['emparejado_alcampo_con_promo'], t['emparejado_carrefour_lista'])})")
    base, est = t["cesta_completa_carrefour_lista"], t["estimacion_cesta_completa_alcampo"]
    out += ["", "Cesta completa (lo no emparejado y lo de peso cuentan al precio de Carrefour en los dos lados):",
            f"  Carrefour, precio de lista:  {_eur(base)}",
            f"  Alcampo, estimación:         {_eur(est)}   ({_pct(est, base)})"]
    sd = tt.get("productos_sin_descuentos")
    if sd and abs(sd - base) > 0.05 * sd:
        out.append(f"  (Ojo: el pedido dice {_eur(sd)} sin descuentos; la diferencia suele venir de productos no entregados o sustituidos.)")
    if envio_alcampo is not None:
        out.append(f"  Alcampo con envío ({_eur(envio_alcampo)}, supuesto que indicaste): {_eur(est + envio_alcampo)}   "
                   f"frente a Carrefour con el envío que pagaste ({_eur(tt.get('envio_pagado') or 0)}): {_eur(base + (tt.get('envio_pagado') or 0))}")
    else:
        out.append("  Envío de Alcampo NO incluido: aún no se conoce (indícalo con --envio-alcampo).")
    por_dif = sorted(r["filas"], key=lambda f: f["coste_con_promo"] - f["carrefour_lista"])
    def fila(f):
        return (f"  {f['nombre'][:60]} x{f['cantidad']}: Carrefour {_eur(f['carrefour_lista'])} | Alcampo {_eur(f['coste_con_promo'])}\n"
                f"     <- {f['alcampo']['nombre'][:80]} [{f['alcampo'].get('envase') or '?'}] a {_eur(f['alcampo']['precio'])} ({f['formato']})"
                + _texto_promos(f))
    alc = [fila(f) for f in por_dif if f["coste_con_promo"] < f["carrefour_lista"]][:8]
    car = [fila(f) for f in por_dif[::-1] if f["coste_con_promo"] > f["carrefour_lista"]][:8]
    out += ["", "Donde Alcampo sale MÁS barato:"] + (alc or ["  (ninguno)"])
    out += ["", "Donde Carrefour sale MÁS barato:"] + (car or ["  (ninguno)"])
    avisos = [
              f"{sum(1 for f in r['filas'] if f['formato'].startswith('ajustado'))} con tamaño distinto (coste ajustado por precio por unidad)",
              f"{sum(1 for f in r['filas'] if not f['misma_marca'])} con otra marca (marcas blancas o equivalentes)",
              f"{sum(1 for f in r['filas'] if f['promo_aplicada'])} con promoción por cantidad aplicada"]
    out += ["", "Avisos: " + "; ".join(avisos) + ".", "No incluye: descuentos de cliente, cheque ahorro, promociones de pedido ni el envío de Alcampo."]
    grandes = sorted((f for f in r["filas"] if f["carrefour_lista"] and abs(f["coste_con_promo"] / f["carrefour_lista"] - 1) >= 0.4),
                     key=lambda f: f["coste_con_promo"] / f["carrefour_lista"])
    if grandes:
        out += ["", "DIFERENCIAS GRANDES (±40 %): comprueba que son el mismo producto y el mismo envase:"]
        for f in grandes[:14]:
            c = f["alcampo"]
            out.append(f"  {f['nombre'][:70]} x{f['cantidad']}: Carrefour {_eur(f['carrefour_lista'])}\n"
                       f"     Alcampo {_eur(f['coste_con_promo'])} <- {c['nombre'][:70]} [{c.get('envase') or '?'}] a {_eur(c['precio'])}/ud "
                       f"({f['formato']}; {'misma marca' if f['misma_marca'] else 'otra marca'})")
    if r["a_revisar"]:
        out += ["", "A REVISAR (equivalencia laxa o formato sin comprobar; NO cuentan en los totales). Confírmalas con: python alcampo_comparar.py confirmar"]
        for f in r["a_revisar"]:
            c = f["alcampo"]
            out.append(f"  {f['nombre'][:45]} x{f['cantidad']} Carrefour {_eur(f['carrefour_lista'])}\n"
                       f"     -> {c['nombre'][:60]} [{c.get('envase') or '?'}] {_eur(c['precio'])} ({f['nivel']}, {f['formato']})")
    if r["sin_equivalente"]:
        out += ["", "Sin equivalente en Alcampo (o no encontrado):"] + [f"  {s['nombre'][:60]} x{s['cantidad']}" for s in r["sin_equivalente"][:15]]
    return "\n".join(out)


def _pct(a, b):
    return f"{(a - b) / b * 100:+.1f} %".replace(".", ",") if b else "—"


# ================================================================ script de consola (se genera con tus búsquedas dentro)

PLANTILLA_JS = r'''// Alcampo: busca en compraonline.alcampo.es los productos de tu pedido de Carrefour y descarga sus precios.
//
// Se ejecuta en TU navegador. Solo LEE precios públicos (no inicia sesión, no toca tu cesta, no envía nada a ningún sitio):
// únicamente descarga un fichero en tu PC. Hace una búsqueda cada 1,5-2,5 s y se detiene solo si el servidor empieza a rechazarlas.
//
//  1) Abre https://www.compraonline.alcampo.es y comprueba que tienes puesto tu código postal / entrega a domicilio.
//     (Los precios dependen de la zona de entrega.)
//  2) Abre la consola (F12 -> pestaña "Consola"), pega este script ENTERO y pulsa Intro.
//     Chrome puede pedirte que escribas "allow pasting" antes de dejarte pegar: escríbelo, Intro, y vuelve a pegar.
//  3) Espera. Al terminar se descarga alcampo_resultados.json. Guárdalo junto a alcampo_comparar.py.
(async function () {
  const CONSULTAS = __CONSULTAS__;
  const BASE = "https://www.compraonline.alcampo.es";
  const VERSION_APP = "2.0.0-2026-10-02-07h59m35s-c399fee2";
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const log = (...a) => console.log("%c[Alcampo]", "color:#e2001a;font-weight:bold", ...a);
  const uuid = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

  if (location.origin !== BASE) {
    console.error("[Alcampo] Abre primero " + BASE + " y vuelve a pegar el script.");
    return;
  }

  let bloqueado = false;
  async function pedir(ruta) {
    for (let intento = 1; intento <= 2; intento++) {
      let r;
      bloqueado = false;
      try {
        r = await fetch(BASE + ruta, {
          credentials: "include",
          headers: { Accept: "application/json; charset=utf-8", "ecom-request-source": "web",
                     "ecom-request-source-version": VERSION_APP, "client-route-id": uuid(), "page-view-id": uuid() },
        });
      } catch (e) {
        await esperar(3000);
        continue;
      }
      if (r.ok) return r.json();
      if (r.status === 405 || r.status === 202) {      // el WAF nos frena: esperar bastante y probar una sola vez más
        bloqueado = true;
        await esperar(15000);
        continue;
      }
      if (r.status === 429 || r.status >= 500) {
        await esperar(4000 * intento);
        continue;
      }
      throw new Error("HTTP " + r.status);
    }
    throw new Error(bloqueado ? "bloqueo del WAF (405)" : "sin respuesta");
  }

  const num = (x) => { const v = parseFloat(x); return isNaN(v) ? null : v; };
  function normalizar(p) {
    const up = p.unitPrice || {};
    return {
      sku: p.retailerProductId, nombre: p.name || "", marca: p.brand || "", envase: p.packSizeDescription || "",
      precio: num((p.price || {}).amount), unidad: up.unitName || null, precio_unidad: num(((up.price) || {}).amount),
      disponible: !!p.available,
      promos: (p.promotions || []).map((x) => ({ tipo: x.type, descripcion: x.description,
                                                  cantidad_requerida: x.requiredProductQuantity === undefined ? null : x.requiredProductQuantity })),
      categoria: (p.categoryPath || []).join(" > "),
    };
  }
  function parsear(j, maximo) {
    const vistos = new Set(), out = [];
    for (const g of j.productGroups || []) {
      for (const p of g.decoratedProducts || []) {
        if (vistos.has(p.productId)) continue;
        vistos.add(p.productId);
        out.push(normalizar(p));
      }
    }
    return out.slice(0, maximo);
  }

  let destino = null;
  try {
    const c = await pedir("/api/cart/v1/carts/active");
    destino = (c.defaultCheckoutGroup || {}).shippingGroupType || null;
  } catch (e) {}
  log("Zona de entrega detectada: " + (destino || "no se ha podido leer") + ". " + CONSULTAS.length + " búsquedas por hacer.");
  if (!destino) log("AVISO: no se ve la zona de entrega. Si los precios salen raros, elige tu código postal en la web y repite.");

  const resultados = {}, errores = [];
  let seguidos = 0, parada = false;
  for (let i = 0; i < CONSULTAS.length; i++) {
    const q = CONSULTAS[i];
    try {
      const j = await pedir("/api/webproductpagews/v6/product-pages/search?includeAdditionalPageInfo=true&maxPageSize=300&maxProductsToDecorate=50&q=" +
                            encodeURIComponent(q) + "&tag=web");
      resultados[q] = parsear(j, 30);
      seguidos = 0;
    } catch (e) {
      errores.push(q + " (" + e.message + ")");
      seguidos++;
      if (seguidos >= 3) {                              // 3 fallos seguidos: seguir solo empeora el bloqueo
        parada = true;
        log("PARADA: 3 búsquedas seguidas fallaron. Guardo lo que hay (" + Object.keys(resultados).length + " búsquedas) y paro para no empeorar el bloqueo.");
        break;
      }
    }
    if ((i + 1) % 10 === 0 || i + 1 === CONSULTAS.length) log((i + 1) + "/" + CONSULTAS.length + " búsquedas");
    await esperar(1500 + Math.random() * 1000);
  }
  if (errores.length) log("AVISO: " + errores.length + " búsquedas fallaron: " + errores.slice(0, 5).join(" | "));
  if (Object.keys(resultados).length === 0) {
    console.error("[Alcampo] No se obtuvo ningún resultado: no se descarga nada. Comprueba que estás en compraonline.alcampo.es con la página cargada.");
    return;
  }
  const salida = { version: 1, fecha: new Date().toISOString(), destino, incompleto: parada, resultados };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(salida)], { type: "application/json" }));
  a.download = "alcampo_resultados.json";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  log("LISTO: " + Object.keys(resultados).length + " búsquedas guardadas en alcampo_resultados.json (carpeta Descargas).");
})();
'''


def generar_js(consultas, ruta):
    """Escribe el script de consola con las búsquedas ya incluidas (así no hace falta ningún selector de ficheros)."""
    Path(ruta).write_text(PLANTILLA_JS.replace("__CONSULTAS__", json.dumps(consultas, ensure_ascii=False)), encoding="utf-8")


# ================================================================ línea de comandos

def ficheros_resultados(ruta):
    """alcampo_resultados.json y sus copias ('alcampo_resultados (1).json'...), de más antiguo a más reciente."""
    cand = {}
    for f in ([Path(ruta)] if Path(ruta).is_file() else []) + list(Path.cwd().glob("alcampo_resultados*.json")) + \
             list((Path.home() / "Downloads").glob("alcampo_resultados*.json")):
        cand[f.resolve()] = f
    return sorted(cand.values(), key=lambda x: x.stat().st_mtime)


def cargar_resultados(ruta):
    """Fusiona todos los ficheros de resultados (el más reciente gana). Devuelve (resultados, ficheros, destino, fecha)."""
    fich, res, destino, fecha = ficheros_resultados(ruta), {}, None, None
    for f in fich:
        j = json.loads(f.read_text(encoding="utf-8"))
        res.update(j.get("resultados") or {})
        destino, fecha = j.get("destino") or destino, j.get("fecha") or fecha
    return res, fich, destino, fecha


def cmd_consultas(a):
    h, ruta = cargar_historial(a.historial)
    p = elegir_pedido(h, a.pedido)
    qs = consultas_del_pedido(p)
    if a.sin_equivalente:
        res, fich, _, _ = cargar_resultados(a.resultados)
        if not fich:
            raise SystemExit("Primero haz el paso normal (consultas -> consola -> comparar): hace falta alcampo_resultados.json.")
        sin = comparar_pedido(p, res)["sin_equivalente"]
        qs = [q for q in dict.fromkeys(q for x in sin for q in consultas_extra(x["nombre"])) if q not in res]
        print(f"{len(sin)} líneas sin equivalente -> {len(qs)} búsquedas nuevas (marca / primera palabra).")
        if not qs:
            print("No hay búsquedas nuevas que probar.")
            return 0
    elif a.faltan:
        hechas = cargar_resultados(a.resultados)[0]
        total = len(qs)
        qs = [q for q in qs if q not in hechas]
        print(f"Ya tienes {total - len(qs)} de {total} búsquedas; quedan {len(qs)}.")
        if not qs:
            print("No falta ninguna: ya puedes ejecutar 'comparar'.")
            return 0
    Path(a.consultas).write_text(json.dumps({"version": 1, "pedido": p.get("id"), "consultas": qs}, ensure_ascii=False, indent=1), encoding="utf-8")
    generar_js(qs, a.script)
    print(f"Historial: {ruta}\nPedido elegido: {p.get('id')} ({str(p.get('fecha_pedido') or '')[:10]}), {len(p.get('lineas') or [])} líneas.")
    print(f"Escrito {a.script} con {len(qs)} búsquedas.")
    print("Ahora: abre compraonline.alcampo.es en Chrome (con tu código postal puesto), F12 -> Consola, pega el CONTENIDO de ese fichero y pulsa Intro.")
    return 0


def cmd_confirmar(a):
    """Pregunta, línea a línea, si el candidato de Alcampo vale. Se guarda en --decisiones y no se vuelve a preguntar."""
    h, _ = cargar_historial(a.historial)
    p = elegir_pedido(h, a.pedido)
    res, fich, _, _ = cargar_resultados(a.resultados)
    if not fich:
        raise SystemExit("Faltan los resultados de Alcampo: haz antes el paso normal (consultas -> consola).")
    dec = cargar_decisiones(a.decisiones)
    pend = [f for f in comparar_pedido(p, res, dec)["a_revisar"] if f["nombre"] not in dec]
    if not pend:
        print("Nada pendiente de confirmar.")
        return 0
    lineas = {l["nombre"]: l for l in p.get("lineas") or []}
    print(f"{len(pend)} líneas por confirmar. En cada una: s = sí, vale el 1 · 2 o 3 = vale ese otro · n = ninguno vale · Intro = saltar · q = salir.\n")
    for i, f in enumerate(pend, 1):
        l = lineas[f["nombre"]]
        cands = emparejar(l, pool_de_linea(l, res), n=3)
        print(f"[{i}/{len(pend)}] Carrefour: {l['nombre']}  x{l['cantidad']}  (lista {_eur(valor_lista(l))})")
        for k, e in enumerate(cands, 1):
            c = e["alcampo"]
            print(f"   {k}) {c['nombre'][:80]} [{c.get('envase') or '?'}] {_eur(c['precio'])}  -> tu cantidad costaría {_eur(e['coste_con_promo'])}\n"
                  f"      ({e['nivel']}, {e['formato']})")
        try:
            resp = input("   ¿Vale? > ").strip().lower()
        except EOFError:
            resp = "q"
        if resp == "q":
            break
        if resp in ("n", "no"):
            dec[l["nombre"]] = {"decision": "no"}
        elif resp in ("s", "si", "sí", "1", "2", "3"):
            k = 1 if resp in ("s", "si", "sí") else int(resp)
            if k <= len(cands):
                dec[l["nombre"]] = {"decision": "si", "sku": cands[k - 1]["alcampo"].get("sku"), "alcampo": cands[k - 1]["alcampo"]["nombre"]}
        guardar_decisiones(a.decisiones, dec)
        print()
    print("Guardado en " + a.decisiones + ". Ahora: python alcampo_comparar.py comparar")
    return 0


def cmd_comparar(a):
    h, _ = cargar_historial(a.historial)
    p = elegir_pedido(h, a.pedido)
    res, fich, destino, fecha = cargar_resultados(a.resultados)
    if not fich:
        raise SystemExit(f"No encuentro {a.resultados}. Primero: python alcampo_comparar.py consultas, y pega alcampo_exportar_listo.js en la consola de Alcampo (paso 2).")
    faltan = [q for q in consultas_del_pedido(p) if q not in res]
    r = comparar_pedido(p, res, cargar_decisiones(a.decisiones))
    print("Resultados de Alcampo: " + ", ".join(f.name for f in fich))
    if faltan:
        print(f"AVISO: faltan {len(faltan)} búsquedas de este pedido (sus productos saldrán como 'sin equivalente'). "
              "Complétalas con: python alcampo_comparar.py consultas --faltan")
    print(informe(p, r, destino, str(fecha or "")[:10], a.envio_alcampo))
    Path(a.salida).write_text(json.dumps({"pedido": p.get("id"), **r}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDetalle completo: {a.salida}")
    return 0


def motivo_rechazo(o, c):
    """Por qué _parecido (modo laxo) descarta a un candidato, en una frase; mismas comprobaciones y en el mismo orden."""
    if not o["head"] or (c["head"] != o["head"] and o["head"] not in (c.get("ini") or [])):
        return f"el tipo no coincide (original '{o['head']}', candidato '{c['head']}')"
    if not o["attrs"] <= c["attrs"]:
        return f"le falta un atributo: {sorted(o['attrs'] - c['attrs'])}"
    if o["formatos"] and c["formatos"] and not (o["formatos"] & c["formatos"]):
        return "formato de envase distinto"
    if c["estado"] == "fresco" and not o["fresco_probable"]:
        return "el candidato es fresco y el original no"
    if o["estado"] and c["estado"] and o["estado"] != c["estado"]:
        return f"estado distinto ({o['estado']} frente a {c['estado']})"
    if o["usos"] and not (o["usos"] & c["usos"]):
        return "uso distinto"
    sim = len(o["resto"] & (c["resto_total"] | {c["head"]})) / len(o["resto"]) if o["resto"] else 1.0
    if sim < 0.25:
        return f"pocas palabras en común ({sim:.0%}); le faltan {sorted(o['resto'] - c['resto_total'] - {c['head']})}"
    return "aceptable en modo laxo (se descarta por no estar disponible o sin precio)"


def cmd_diagnostico(a):
    """Informe corto para saber POR QUÉ no se empareja: búsquedas vacías, y candidatos que devolvió Alcampo para las líneas sin equivalente."""
    h, _ = cargar_historial(a.historial)
    p = elegir_pedido(h, a.pedido)
    res, fich, _, _ = cargar_resultados(a.resultados)
    qs = consultas_del_pedido(p)
    vacias = [q for q in qs if q in res and not res[q]]
    print(f"Ficheros: {len(fich)}. Búsquedas del pedido: {len(qs)}; con resultados: {sum(1 for q in qs if res.get(q))}; "
          f"vacías: {len(vacias)}; sin hacer: {sum(1 for q in qs if q not in res)}.")
    if vacias:
        print("Vacías (primeras 8): " + " | ".join(vacias[:8]))
    cuenta, todos = {}, {}
    for lista in res.values():
        for c in lista:
            todos[c["sku"]] = c
    for c in todos.values():
        for x in c.get("promos") or []:
            k = (x.get("tipo"), x.get("descripcion"))
            cuenta[k] = cuenta.get(k, 0) + 1
    print(f"\nPromociones vistas en {len(todos)} productos de Alcampo: {sum(cuenta.values())} ({len(cuenta)} textos distintos). Los 15 más frecuentes:")
    for (tipo, desc), n_ in sorted(cuenta.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {n_:3} x [{tipo}] {desc}")
    n = 0
    for l in p.get("lineas") or []:
        if es_a_peso(l):
            continue
        qs_l = consultas_de_linea(l["nombre"]) + consultas_extra(l["nombre"])
        pool = {c["sku"]: c for q in qs_l for c in res.get(q) or []}
        if emparejar(l, list(pool.values())) is not None:
            continue
        n += 1
        if n > a.lineas:
            break
        print(f"\n- {l['nombre']}\n  búsquedas: " + "; ".join(f"'{q}'={len(res[q])}" for q in qs_l if q in res))
        pf = _perfil(l["nombre"], "", l.get("venta"))
        print(f"  tipo={pf['head']} atributos={sorted(pf['attrs'])} resto={sorted(pf['resto'])}")
        if not pool:
            print("    (ninguna búsqueda devolvió productos)")
        o_perf = dict(pf, tamano=None)
        for c in list(pool.values())[:3]:
            pc = dict(_perfil(limpiar_nombre_alcampo(c["nombre"]), c.get("marca", "")), tamano=None)
            print(f"    candidato: {c['nombre'][:60]} [{c['marca']}] disp={c['disponible']} precio={c['precio']}\n"
                  f"       descartado porque: {motivo_rechazo(o_perf, pc)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compara un pedido de Carrefour con los precios de Alcampo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre, f in (("consultas", cmd_consultas), ("comparar", cmd_comparar), ("diagnostico", cmd_diagnostico), ("confirmar", cmd_confirmar)):
        s = sub.add_parser(nombre)
        s.add_argument("--historial", help="ruta de historial_pedidos.json (por defecto lo busca solo)")
        s.add_argument("--pedido", help="id del pedido de Carrefour (por defecto, el más reciente con 20 líneas o más)")
        s.add_argument("--decisiones", default="emparejamientos_alcampo.json", help="dónde se guardan tus confirmaciones")
        if nombre == "confirmar":
            s.add_argument("--resultados", default="alcampo_resultados.json")
        elif nombre == "diagnostico":
            s.add_argument("--resultados", default="alcampo_resultados.json")
            s.add_argument("--lineas", type=int, default=8, help="cuántas líneas sin equivalente detallar")
        elif nombre == "consultas":
            s.add_argument("--consultas", default="alcampo_consultas.json")
            s.add_argument("--script", default="alcampo_exportar_listo.js")
            s.add_argument("--sin-equivalente", action="store_true", help="solo búsquedas cortas de rescate para las líneas sin equivalente")
            s.add_argument("--faltan", action="store_true", help="solo las búsquedas que aún no están en alcampo_resultados*.json")
            s.add_argument("--resultados", default="alcampo_resultados.json")
        else:
            s.add_argument("--resultados", default="alcampo_resultados.json")
            s.add_argument("--salida", default="comparacion_alcampo.json")
            s.add_argument("--envio-alcampo", type=float, default=None, help="coste de envío de Alcampo en euros, si lo conoces")
        s.set_defaults(f=f)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
