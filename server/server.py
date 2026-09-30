# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.2,<3", "httpx>=0.27", "playwright>=1.45"]
# ///
"""MCP COTO: busca productos, cotiza la lista y carga el carrito de Coto Digital.

Nunca finaliza la compra: el pago y la confirmación los hace el usuario en la web.
Proyecto no oficial, sin relación con Coto.
"""
import asyncio
import json
import logging
import math
import os
import shutil
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

BASE = "https://www.coto.com.ar"
SEARCH_URL = f"{BASE}/sitios/cdigi/categoria"
REST = "/rest/model/atg"
DIR = Path(__file__).parent
# Datos de cada usuario: COTO_DATA_DIR (desarrollo) > CLAUDE_PLUGIN_DATA (plugin instalado) > carpeta del script
DATA = Path(os.environ.get("COTO_DATA_DIR") or os.environ.get("CLAUDE_PLUGIN_DATA") or DIR)
DATA.mkdir(parents=True, exist_ok=True)
LISTA = DATA / "lista.json"
EJEMPLO = DIR / "lista.ejemplo.json"
PERFIL = DATA / ".coto_perfil"  # perfil de Chrome propio del MCP (guarda la sesión de Coto)
COOKIES = DATA / ".coto_cookies.json"  # copia de las cookies de sesión para sobrevivir reinicios
VECES_POR_MES = {"mensual": 1, "quincenal": 2, "semanal": 4}
HEADERS = {"User-Agent": "Mozilla/5.0"}

logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = MCPServer("coto")


# ---------------------------------------------------------------- catálogo (sin login)

def _find_records(o):
    if isinstance(o, dict):
        if o.get("records") and "totalNumRecs" in o:
            return o["records"]
        for v in o.values():
            if (r := _find_records(v)) is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            if (r := _find_records(v)) is not None:
                return r
    return None


def _first_attrs(o):
    """Primer diccionario de atributos que tenga precio (sirve para búsqueda y detalle)."""
    if isinstance(o, dict):
        a = o.get("attributes")
        if isinstance(a, dict) and "sku.repositoryId" in a:
            return a
        for v in o.values():
            if (r := _first_attrs(v)) is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            if (r := _first_attrs(v)) is not None:
                return r
    return None


def _parse(a):
    g = lambda k: (a.get(k) or [""])[0]
    try:
        p = json.loads(g("sku.dtoPrice078") or "{}")
    except json.JSONDecodeError:
        p = {}
    promo, precio_promo = "", None
    try:
        d = json.loads(g("product.dtoDescuentos") or "[]")
        if d:
            promo = (d[0].get("textoDescuento") or "").strip() + " " + (d[0].get("textoLlevando") or "").strip()
            precio_promo = float(d[0].get("precioDesc") or 0) or None
    except (json.JSONDecodeError, ValueError):
        pass
    if precio_promo and p.get("precioLista") and precio_promo >= p["precioLista"]:
        promo, precio_promo = "", None  # etiqueta de "promo" sin descuento real
    return {
        "sku": g("sku.repositoryId"),
        "prod": g("product.repositoryId"),
        "nombre": g("product.displayName").strip(),
        "marca": g("product.brand"),
        "precio": p.get("precioLista"),
        "precio_ref": float(g("sku.referencePrice") or 0),
        "promo": promo.strip(),
        "precio_promo": precio_promo,
        "pesable": g("product.unidades.esPesable") == "1",
    }


def _json(resp):
    try:
        return json.loads(resp.content.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(resp.content.decode("latin-1"))


async def _buscar(client, termino, n):
    r = await client.get(SEARCH_URL, params={"_dyncharset": "utf-8", "Dy": 1, "Ntt": termino, "Nrpp": n, "format": "json"})
    out = []
    for rec in _find_records(_json(r)) or []:
        a = _first_attrs(rec)
        if a:
            out.append(_parse(a))
    return out


async def _detalle(client, sku):
    num = sku.replace("sku", "")
    r = await client.get(f"{BASE}/sitios/cdigi/productos/_/R-{num}-{num}-200", params={"Dy": 1, "format": "json"})
    a = _first_attrs(_json(r))
    return _parse(a) if a else None


def _precio_efectivo(p):
    return p["precio_promo"] or p["precio"] or 0


async def _resolver(client, item):
    """Elige qué SKU comprar para un ítem. Con 'alternativas' toma el más barato (comparar solo
    productos de la misma unidad, ej. cortes x kg); con 'precio_max' no compra si todo está más caro.
    Devuelve (item con el SKU elegido, detalle) o (None, motivo)."""
    skus = [item["sku"]] + item.get("alternativas", [])
    dets = await asyncio.gather(*(_detalle(client, s) for s in skus), return_exceptions=True)
    ok = [d for d in dets if d and not isinstance(d, Exception) and d["precio"]]
    if not ok:
        return None, f"⚠️ {item['id']}: no se encontró {item['sku']} (¿sin stock o dado de baja?)"
    mejor = min(ok, key=_precio_efectivo)
    tope = item.get("precio_max")
    if tope and _precio_efectivo(mejor) > tope:
        return None, (f"⏸ {item['id']}: caro hoy, lo más barato es {mejor['nombre']} a "
                      f"${_precio_efectivo(mejor):,.0f} (tope ${tope:,.0f}); no se compra")
    return {**item, "sku": mejor["sku"], "nombre": mejor["nombre"]}, mejor


def _fmt(p):
    promo = f" | PROMO {p['promo']} → ${p['precio_promo']:,.0f}" if p["precio_promo"] else ""
    ref = f" (${p['precio_ref']:,.0f}/kg-L)" if p["precio_ref"] else ""
    peso = " [x kg]" if p["pesable"] else ""
    return f"{p['sku']} | {p['nombre']}{peso} | ${p['precio'] or 0:,.0f}{ref}{promo}"


# ---------------------------------------------------------------- lista

def _leer_lista():
    if not LISTA.exists():
        return {"items": []}
    return json.loads(LISTA.read_text(encoding="utf-8"))


def _guardar_lista(data):
    LISTA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _items(frecuencia):
    """frecuencia: mensual | quincenal | semanal | todo, o varias separadas por coma
    (ej. 'quincenal,semanal' para la compra de mitad de mes)."""
    items = _leer_lista()["items"]
    if frecuencia in (None, "", "todo"):
        return items
    pedidas = {f.strip() for f in frecuencia.split(",")}
    if not pedidas <= VECES_POR_MES.keys():
        raise ValueError("frecuencia debe ser mensual, quincenal, semanal, todo o una combinación con comas")
    return [i for i in items if i["frecuencia"] in pedidas]


def _normalizar_cantidad(cantidad, pesable):
    if pesable:
        return max(0.25, math.ceil(float(cantidad) * 4) / 4)  # Coto vende por peso en saltos de 0,25 kg
    return max(1, int(math.ceil(float(cantidad))))


# ---------------------------------------------------------------- navegador (con login)

_pw = None
_ctx = None

JS_API = """
async ([path, method, body]) => {
  const t = await (await fetch('/rest/model/atg/rest/SessionConfirmationActor/getSessionConfirmationNumber',
                               {credentials: 'include', cache: 'no-store'})).text();
  const m = t.match(/-?\\d+/);
  const sep = path.includes('?') ? '&' : '?';
  const url = path + sep + 'pushSite=CotoDigital' + (m ? '&_dynSessConf=' + m[0] : '');
  const r = await fetch(url, {method, credentials: 'include', cache: 'no-store',
    headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-cache'},
    body: body ? JSON.stringify(body) : undefined});
  return await r.text();
}
"""


async def _pagina():
    global _pw, _ctx
    if _ctx is None:
        from playwright.async_api import async_playwright
        _pw = await async_playwright().start()
        _ctx = await _pw.chromium.launch_persistent_context(
            str(PERFIL), channel="chrome", headless=False, viewport=None,
            args=["--start-maximized"])
        # Chrome borra las cookies de sesión (JSESSIONID = login de Coto) al cerrarse: las restauramos
        if COOKIES.exists():
            try:
                await _ctx.add_cookies([{k: v for k, v in c.items() if k != "partitionKey"}
                                        for c in json.loads(COOKIES.read_text(encoding="utf-8"))])
            except Exception:
                pass  # si Coto venció la sesión, se pide login de nuevo
    page = _ctx.pages[0] if _ctx.pages else await _ctx.new_page()
    if not page.url.startswith(BASE):
        await page.goto(BASE + "/", wait_until="domcontentloaded")
    return page


async def _api(page, path, method="GET", body=None):
    txt = await page.evaluate(JS_API, [REST + path, method, body])
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {"raw": txt[:500]}


async def _logueado(page):
    """(logueado, carrito). El carrito anónimo responde sin error, así que el login se confirma
    como lo hace la web: getMyProfile con securityStatus > 2. Si está logueado, guarda las cookies."""
    perfil = await _api(page, "/actors/cProfileActor/getMyProfile")
    perfil = perfil.get("output", perfil) if isinstance(perfil.get("output"), dict) else perfil
    try:
        ok = int(perfil.get("securityStatus") or 0) > 2
    except (TypeError, ValueError):
        ok = False
    r = await _api(page, "/actors/cCarritoActor/getCarrito")
    if isinstance(r.get("output"), dict):  # a veces el carrito viene envuelto en "output"
        r = r["output"]
    if ok:
        COOKIES.write_text(json.dumps(await _ctx.cookies()), encoding="utf-8")
    return ok, r


# ---------------------------------------------------------------- tools

@mcp.tool()
async def buscar_producto(termino: str, cantidad: int = 15, ordenar_por_precio_kg: bool = True) -> str:
    """Busca productos en Coto Digital. Devuelve SKU, nombre, precio, precio por kg/L y promos."""
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as c:
        res = [p for p in await _buscar(c, termino, max(cantidad, 20)) if p["precio"]]
    if ordenar_por_precio_kg:
        res.sort(key=lambda p: p["precio_ref"] or 1e12)
    return "\n".join(_fmt(p) for p in res[:cantidad]) or "Sin resultados."


@mcp.tool()
def ver_lista(frecuencia: str = "todo") -> str:
    """Muestra la lista de compra. frecuencia: mensual | quincenal | semanal | todo."""
    lineas = []
    if not _leer_lista()["items"]:
        return ("La lista está vacía. Armala con buscar_producto + editar_item "
                "(skill armar-lista) o partí del ejemplo con usar_lista_ejemplo().")
    for i in _items(frecuencia):
        u = "kg" if i["pesable"] else "u"
        extra = ""
        if i.get("alternativas"):
            extra += f" [el más barato de {len(i['alternativas']) + 1} opciones]"
        if i.get("precio_max"):
            extra += f" [solo si cuesta hasta ${i['precio_max']:,.0f}]"
        lineas.append(f"[{i['frecuencia']}] {i['id']}: {i['nombre']} — {i['cantidad']} {u} ({i['sku']}){extra}")
    return "\n".join(lineas)


@mcp.tool()
async def cotizar(frecuencia: str = "todo") -> str:
    """Consulta precios actuales de la lista. Con 'todo' estima el gasto mensual
    (mensual x1 + quincenal x2 + semanal x4). Usa precio promo cuando existe."""
    items = _items(frecuencia)
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as c:
        resueltos = await asyncio.gather(*(_resolver(c, i) for i in items))
    subt = {k: 0.0 for k in VECES_POR_MES}
    lineas = []
    for i, (ri, d) in zip(items, resueltos):
        if ri is None:
            lineas.append(d)
            continue
        total = _precio_efectivo(d) * i["cantidad"]
        subt[i["frecuencia"]] += total
        promo = f" PROMO {d['promo']}" if d["precio_promo"] else ""
        cual = f" → {d['nombre']}" if i.get("alternativas") else ""
        lineas.append(f"[{i['frecuencia']}] {i['id']}: {i['cantidad']} x ${_precio_efectivo(d):,.0f} = ${total:,.0f}{promo}{cual}")
    lineas.append("")
    for k, v in subt.items():
        if v:
            lineas.append(f"Subtotal {k} (por compra): ${v:,.0f}")
    if frecuencia in ("todo", "", None):
        mes = sum(v * VECES_POR_MES[k] for k, v in subt.items())
        lineas.append(f"TOTAL ESTIMADO DEL MES: ${mes:,.0f}")
    lineas.append("Nota: promos tipo 3x2 se calculan como precio promedio; pesables se cobran por peso real.")
    return "\n".join(lineas)


@mcp.tool()
async def editar_item(id: str, sku: str = "", cantidad: float = 0, nombre: str = "", frecuencia: str = "",
                      busqueda: str = "") -> str:
    """Modifica un ítem de la lista (cambiar producto por otro SKU, cantidad, nombre o frecuencia).
    Si el id no existe, lo agrega (requiere sku, cantidad y frecuencia). 'busqueda' es el término
    genérico (ej. 'arroz integral') que se usa para proponer reemplazos si no hay stock."""
    data = _leer_lista()
    item = next((i for i in data["items"] if i["id"] == id), None)
    nuevo = item is None
    if nuevo:
        if not (sku and cantidad and frecuencia):
            return "Para agregar un ítem nuevo necesito sku, cantidad y frecuencia."
        item = {"id": id}
        data["items"].append(item)
    if frecuencia:
        if frecuencia not in VECES_POR_MES:
            return "frecuencia debe ser mensual, quincenal o semanal"
        item["frecuencia"] = frecuencia
    if sku:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as c:
            d = await _detalle(c, sku)
        if not d:
            return f"No encontré el SKU {sku} en Coto."
        item.update(sku=d["sku"], pesable=d["pesable"], nombre=nombre or d["nombre"])
    elif nombre:
        item["nombre"] = nombre
    if cantidad:
        item["cantidad"] = _normalizar_cantidad(cantidad, item.get("pesable", False))
    if busqueda:
        item["busqueda"] = busqueda
    _guardar_lista(data)
    return ("Agregado: " if nuevo else "Actualizado: ") + json.dumps(item, ensure_ascii=False)


@mcp.tool()
def usar_lista_ejemplo(reemplazar: bool = False) -> str:
    """Copia la lista de ejemplo (compra mensual de una persona en déficit calórico) como punto de
    partida. No pisa una lista existente salvo reemplazar=True."""
    if LISTA.exists() and _leer_lista()["items"] and not reemplazar:
        return "Ya tenés una lista. Usá reemplazar=True si querés pisarla con el ejemplo."
    shutil.copyfile(EJEMPLO, LISTA)
    return "Lista de ejemplo copiada:\n" + ver_lista()


@mcp.tool()
def quitar_item(id: str) -> str:
    """Saca un ítem de la lista por su id."""
    data = _leer_lista()
    antes = len(data["items"])
    data["items"] = [i for i in data["items"] if i["id"] != id]
    _guardar_lista(data)
    return f"Quitado {id}." if len(data["items"]) < antes else f"No existe el ítem {id}."


@mcp.tool()
async def iniciar_sesion(esperar_segundos: int = 300) -> str:
    """Abre Chrome en Coto Digital para que el usuario inicie sesión (solo hace falta una vez;
    la sesión queda guardada en el perfil del MCP). Espera hasta que el login se complete."""
    page = await _pagina()
    ok, _ = await _logueado(page)
    if ok:
        return "Ya hay una sesión iniciada en Coto Digital."
    await page.bring_to_front()
    for _ in range(max(1, esperar_segundos // 5)):
        await asyncio.sleep(5)
        try:
            ok, _ = await _logueado(await _pagina())
        except Exception:
            continue  # la página puede estar navegando durante el login
        if ok:
            return "Sesión iniciada correctamente."
    return "Todavía no se detecta el login. Iniciá sesión en la ventana de Chrome y volvé a llamar a iniciar_sesion."


@mcp.tool()
async def diagnostico() -> str:
    """Muestra el estado de la sesión de Coto en el Chrome del MCP: URL, cookies (de sesión o
    persistentes), si la página muestra 'Ingresar' o el usuario, y la respuesta cruda del carrito."""
    import time
    page = await _pagina()
    out = [f"URL: {page.url}"]
    ahora = time.time()
    for ck in await _ctx.cookies([BASE]):
        exp = "sesión" if ck["expires"] in (-1, None) else f"{(ck['expires'] - ahora) / 86400:.1f} días"
        out.append(f"cookie {ck['name']} ({ck['domain']}): {exp}")
    texto = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''")
    marcas = [m for m in ("Ingresar", "Iniciar sesión", "Mi cuenta", "Hola", "Cerrar sesión", "Salir") if m in texto]
    out.append(f"Textos de login en la página: {marcas or 'ninguno'}")
    perfil = await _api(page, "/actors/cProfileActor/getMyProfile")
    perfil = perfil.get("output", perfil) if isinstance(perfil.get("output"), dict) else perfil
    out.append(f"getMyProfile.securityStatus: {perfil.get('securityStatus')} (logueado si > 2), "
               f"nombre: {perfil.get('firstName')}")
    _, r = await _logueado(page)
    out.append("getCarrito: " + json.dumps(r, ensure_ascii=False)[:800])
    return "\n".join(out)


@mcp.tool()
async def ver_carrito() -> str:
    """Muestra el carrito actual de Coto Digital (requiere sesión)."""
    page = await _pagina()
    ok, r = await _logueado(page)
    if not ok:
        return "No hay sesión. Usá iniciar_sesion primero."
    items = r.get("productoItems") or {}
    if not items:
        if "productoItems" in r:
            return "Carrito vacío."
        return "Respuesta inesperada del carrito:\n" + json.dumps(r, ensure_ascii=False)[:1500]
    pesables = {i["sku"] for i in _leer_lista()["items"] if i["pesable"]}
    lineas, total = [], 0.0
    for it in items.values():
        ci = it.get("commerceItem") or {}
        nombre = ci.get("productDisplayName") or ci.get("catalogRefId")
        q = ci.get("quantity") or 0
        # Coto guarda todas las cantidades x1000 (750 = 0,75 kg; 3000 = 3 unidades)
        pesable = ci.get("catalogRefId") in pesables or nombre.strip().lower().endswith("x kg")
        cant = f"{q / 1000:g} kg" if pesable else f"{q / 1000:g} u"
        sub = float(it.get("total") or 0)
        total += sub
        lineas.append(f"{ci.get('catalogRefId')} | {nombre} | {cant} | ${sub:,.0f}")
    lineas.append(f"TOTAL ({len(items)} productos): ${total:,.0f}")
    return "\n".join(lineas)


@mcp.tool()
async def cargar_carrito(frecuencia: str, confirmar: bool = False) -> str:
    """Carga en el carrito de Coto los ítems de la lista para una frecuencia
    (mensual | quincenal | semanal | todo, o combinadas con coma). Compra típica del mes:
    semana 1 'todo', semana 2 'semanal', semana 3 'quincenal,semanal', semana 4 'semanal'.
    Con confirmar=False solo muestra qué haría. Si un producto no tiene stock, propone
    alternativas. La cantidad se FIJA (no se suma a lo que ya haya en el carrito). No finaliza la compra."""
    items = _items(frecuencia)
    if not confirmar:
        return ("Vista previa (no se cargó nada). Llamá de nuevo con confirmar=True para cargar:\n"
                + ver_lista(frecuencia))
    page = await _pagina()
    ok, _ = await _logueado(page)
    if not ok:
        return "No hay sesión. Usá iniciar_sesion primero."
    lineas = []
    elegir = [i for i in items if i.get("alternativas") or i.get("precio_max")]
    if elegir:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as c:
            res = dict(zip((i["id"] for i in elegir), await asyncio.gather(*(_resolver(c, i) for i in elegir))))
        nuevos = []
        for i in items:
            if i["id"] not in res:
                nuevos.append(i)
            elif res[i["id"]][0] is None:
                lineas.append(res[i["id"]][1])
            else:
                nuevos.append(res[i["id"]][0])
        items = nuevos
    for i in items:
        body = {"skuId": i["sku"], "prodId": i["sku"].replace("sku", "prod"),
                "quantity": i["cantidad"], "sucPickUp": None, "cambiaSuc": "true"}
        r = await _api(page, "/actors/cCarritoActor/addOrRemoveItemToOrderV2", "POST", body)
        cod = str(r.get("codigoError"))
        if cod == "0":
            cual = f" ({i['nombre']})" if i.get("alternativas") else ""
            lineas.append(f"✅ {i['id']}: {i['cantidad']}{cual}")
        elif cod == "5":
            lineas.append(f"❌ {i['id']}: falta elegir domicilio/método de entrega en la web")
        elif cod == "2":
            lineas.append(f"❌ {i['id']}: sesión vencida, usá iniciar_sesion")
            break
        else:
            msg = r.get("mensajeError") or str(r)
            lineas.append(f"❌ {i['id']}: {msg}")
            if "stock" in msg.lower():
                lineas.extend(await _reemplazos(i))
    # Verificación: releer el carrito y comparar con lo que se intentó cargar
    _, r = await _logueado(page)
    en_carrito = {(it.get("commerceItem") or {}).get("catalogRefId") for it in (r.get("productoItems") or {}).values()}
    ok_ids = [i for i in items if any(l.startswith(f"✅ {i['id']}:") for l in lineas)]
    faltan = [i["id"] for i in ok_ids if i["sku"] not in en_carrito]
    if faltan:
        lineas.append(f"\n⚠️ VERIFICACIÓN FALLIDA: Coto respondió OK pero no aparecen en el carrito: {', '.join(faltan)}."
                      " Probablemente la sesión no es la de tu cuenta: usá diagnostico / iniciar_sesion.")
    else:
        lineas.append(f"\nVerificado: {len(ok_ids)} productos presentes en el carrito.")
    lineas.append("Revisá el carrito en la ventana de Chrome y finalizá la compra vos.")
    return "\n".join(lineas)


async def _reemplazos(item, n=3):
    """Alternativas más baratas por kg/L para un ítem sin stock (mismo tipo: pesable o no)."""
    termino = item.get("busqueda") or item["nombre"]
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as c:
        res = await _buscar(c, termino, 20)
    res = [p for p in res if p["precio"] and p["sku"] != item["sku"] and p["pesable"] == item["pesable"]]
    res.sort(key=lambda p: p["precio_ref"] or 1e12)
    if not res:
        return [f"   (sin alternativas para '{termino}')"]
    return [f"   ↳ alternativa: {_fmt(p)}" for p in res[:n]] + [
        f"   Para cambiarlo: editar_item(id='{item['id']}', sku=<SKU>) y volver a cargar."]


if __name__ == "__main__":
    mcp.run()
