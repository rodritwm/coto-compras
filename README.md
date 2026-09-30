# Coto Compras — plugin para Claude Code

Hacé la compra del super en [Coto Digital](https://www.coto.com.ar) desde Claude Code: armá tu lista (o un menú y la lista que sale de él), cotizala con precios del día y cargá el carrito. **El pago y la confirmación los hacés vos en la web**: el plugin nunca finaliza una compra.

> Proyecto personal y **no oficial**, sin relación con Coto. Usa endpoints internos de la web de Coto, así que puede dejar de funcionar si cambian el sitio.

## Qué hace

| Herramienta | Para qué |
|---|---|
| `buscar_producto` | Busca en Coto, ordenado por precio por kg/L, con promos |
| `ver_lista` / `editar_item` / `quitar_item` / `usar_lista_ejemplo` | Tu lista de compras (mensual, quincenal y semanal) |
| `cotizar` | Precio actual de la lista y gasto estimado del mes |
| `iniciar_sesion` | Abre Chrome para que entres a tu cuenta de Coto (una vez) |
| `cargar_carrito` | Carga la lista en tu carrito, propone reemplazos sin stock y verifica el resultado |
| `ver_carrito` / `diagnostico` | Ver el carrito y revisar el estado de la sesión |

Skills:
- `/coto-compras:armar-lista`: arma la lista según tus gustos, presupuesto u objetivo (por ejemplo bajar de peso).
- `/coto-compras:compra [semanal]`: cotiza, carga el carrito y verifica.

Extras de la lista: un ítem puede tener `alternativas` (compra el más barato del día, útil para cortes de carne) y `precio_max` (no lo compra si está más caro que eso).

## Requisitos

- [Claude Code](https://claude.com/claude-code)
- [uv](https://docs.astral.sh/uv/getting-started/installation/), que instala Python y las dependencias solo:
  - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Google Chrome instalado
- Una cuenta de Coto Digital con domicilio de entrega o sucursal elegida

## Instalación

Dentro de Claude Code:

```
/plugin marketplace add <usuario-de-github>/coto-compras
/plugin install coto-compras@coto-compras
```

Reiniciá Claude Code y pedile: *"armemos mi lista de Coto"* o *"hacé la compra de esta semana"*.

La primera vez que cargue el carrito se abre una ventana de Chrome aparte (con su propio perfil) para que inicies sesión en Coto.

## Privacidad

Todo corre en tu computadora. Tu lista, el perfil de Chrome y las cookies de Coto se guardan en la carpeta de datos del plugin (`~/.claude/plugins/data/coto-compras-…/`) y no se mandan a ningún servidor aparte de Coto. Tu contraseña la escribís vos en la web de Coto; el plugin no la ve ni la guarda.

## Desarrollo

```
claude --plugin-dir ./coto-compras
```

Para usar otra carpeta de datos, definí `COTO_DATA_DIR`.

## Licencia

MIT
