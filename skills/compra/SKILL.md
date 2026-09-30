---
name: compra
description: Hace la compra del super en Coto Digital con la lista guardada. Cotiza, carga el carrito y verifica. Usar cuando la persona pide hacer la compra, cargar el carrito de Coto o cotizar la lista.
argument-hint: "[todo | semanal | quincenal,semanal | mensual]"
---

# Compra en Coto Digital

Usá las herramientas del MCP `coto`. **Nunca finalices ni pagues la compra**: eso lo hace la persona en la web.

## Qué cargar

Si la persona no dijo qué compra es, preguntá en qué semana del mes está y usá este calendario:

| Semana | `frecuencia` |
|---|---|
| 1 (principio de mes) | `todo` |
| 2 | `semanal` |
| 3 | `quincenal,semanal` |
| 4 | `semanal` |

Si la persona ya dijo qué frecuencia comprar (por ejemplo como argumento: $ARGUMENTS), usala sin preguntar.

## Pasos

1. `ver_lista`. Si está vacía, ofrecé la skill `armar-lista` y pará.
2. `cotizar` con la frecuencia elegida. Mostrá el subtotal y marcá:
   - ítems con `⏸` (caros hoy según su `precio_max`: no se compran),
   - ítems con `⚠️` (no encontrados).
3. `iniciar_sesion`. Si abre Chrome, pedile a la persona que entre con su cuenta de Coto en esa ventana.
4. `ver_carrito`. Si ya tiene productos, preguntá si seguir: `cargar_carrito` fija cantidades de los ítems de la lista pero no borra otros productos.
5. `cargar_carrito(frecuencia, confirmar=True)` solo después de que la persona confirme lo que se va a cargar.
6. Leé la línea de verificación final:
   - `Verificado: N productos` → listo.
   - `VERIFICACIÓN FALLIDA` → corré `diagnostico`; si `securityStatus` no es mayor a 2, la sesión no es válida: `iniciar_sesion` y volvé a cargar.
7. Si hubo productos sin stock, mostrá las alternativas que propuso `cargar_carrito` y, si la persona elige una, `editar_item(id, sku=...)` y volvé a cargar esa frecuencia.
8. Cerrá con el total de `ver_carrito` y recordá que las promos pueden aplicarse recién al finalizar la compra en la web, y que ahí elige entrega y paga.
