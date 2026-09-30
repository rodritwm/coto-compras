---
name: armar-lista
description: Arma o ajusta la lista de compras de Coto según los gustos, el presupuesto y el objetivo de la persona (por ejemplo bajar de peso). Usar cuando no hay lista, cuando quiere cambiar productos o cantidades, o armar un menú y derivar la compra de él.
---

# Armar la lista de compras

La lista vive en el MCP `coto` (`ver_lista`, `editar_item`, `quitar_item`, `usar_lista_ejemplo`). Cada ítem tiene `frecuencia` (`mensual`, `quincenal` o `semanal`) y la cantidad es **por cada compra**.

## 1. Entender a la persona (preguntá solo lo que falte)

- Para cuántas personas es la compra y cuántas comidas hacen por día.
- Qué **no** come o no compra en Coto (por ejemplo pollo y huevos en la pollería). Respetá esto siempre; no lo vuelvas a sugerir.
- Cuánto tiempo quiere cocinar. Por defecto, platos simples: proteína a la plancha + verduras o ensaladas.
- Objetivo: ahorrar, comer más sano, bajar de peso. Si es bajar de peso, pedí sexo, edad, altura, peso y actividad, estimá el gasto con Mifflin-St Jeor y proponé un déficit moderado (~500–1000 kcal por día). Recomendá consultar con un médico o nutricionista, sobre todo con IMC alto.

## 2. Menú primero, lista después

Proponé un menú semanal corto y derivá las cantidades de él: porciones por semana × 4,3 semanas, divididas según la frecuencia. Mostrá el cálculo de los ítems grandes para que la persona pueda corregirlo. Las cantidades suelen quedar altas: si algo parece mucho (pan, leche, latas), preguntá.

## 3. Elegir productos en Coto

- `buscar_producto(termino)` ordena por precio por kg/L. Elegí la mejor relación precio/calidad; para bajar de peso priorizá opciones descremadas, light o integrales y señalá lo calórico (aceite, maní, fiambres).
- Frescos y carnes suelen ser pesables: cantidad en kg, en saltos de 0,25.
- Agregá con `editar_item(id, sku, cantidad, frecuencia, busqueda)`. `busqueda` es un término genérico ("queso blanco light") que sirve para proponer reemplazos si no hay stock.
- Para carne u otros productos con varias opciones equivalentes, se puede editar la lista a mano (archivo `lista.json` en la carpeta de datos del plugin) con `"alternativas": [skus]` (se compra la más barata del día) y `"precio_max"` (no se compra si todo supera ese precio por kg).

## 4. Cerrar

`cotizar("todo")` para mostrar el gasto estimado del mes y ajustar si se pasa del presupuesto. Después ofrecé la skill `compra`.

Si la persona quiere arrancar rápido, `usar_lista_ejemplo()` copia una lista de ejemplo para 1 persona en déficit calórico, que después se ajusta.
