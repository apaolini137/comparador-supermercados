# Comparador de supermercados de España — documento de traspaso (versión 2)

> Escrito el 4 de octubre de 2026, al final de una sesión larga en Claude Code (nube). Sustituye al traspaso anterior (`comparador_supermercados_traspaso_1.md`).
> **[Verificado]** = comprobado con datos reales (capturas HAR del usuario, ejecuciones en su PC o peticiones reales a la web de Alcampo).
> **[Sin verificar]** = hipótesis o dato de fuentes externas.
> Adjunta también **`alcampo_comparar.py` v1.21** (es el único código nuevo de esta sesión; el traspaso anterior hablaba de la v1.1).

---

## 0. Prompt de inicio (pégalo en la conversación nueva junto con este fichero y `alcampo_comparar.py`)

```
Lee el documento adjunto: es el traspaso de un proyecto en curso (un comparador de precios y cestas entre
supermercados de España) y adjunto también alcampo_comparar.py v1.21. Responde siempre en español de España
(tú/vosotros, nunca voseo ni argentinismos). Sigue las normas de trabajo de la sección 10, sobre todo: no me
preguntes lo que ya se ve en los datos, y no des una cifra como definitiva si depende de líneas dudosas.
Si adjunto una captura HAR, tu primer paso es analizarla con el método de la sección 9. Si no adjunto nada,
dime cuál de los pasos de la sección 8 quieres que haga y qué te falta.
```

---

## 1. Resumen en 12 líneas

1. El usuario hace la **compra grande del mes en Carrefour** (online, a domicilio) y quiere saber si **Alcampo** le sale más barato. La pequeña la hace en Mercadona y Lidl.
2. Arquitectura decidida: herramienta **de solo lectura y anónima**, un adaptador por cadena y una librería común de emparejamiento. De momento es **un script de Python** (`alcampo_comparar.py`), no un MCP.
3. **Alcampo ya está comparado de extremo a extremo** con un pedido real de Carrefour (28/09/2026, 44 líneas, 137,78 € pagados). Resultado en la sección 7.
4. **Conclusión provisional:** en precio de estantería Alcampo es ~5 % más barato; en coste real (con los descuentos y el envío gratis que Carrefour le dio) **es un empate técnico (±2 €)**. Con envío de 0,99 € y sin pedido mínimo, Alcampo gana en compras pequeñas.
5. **Alcampo, condiciones verificadas** (cesta anónima en CP 28922): pedido mínimo **0,01 €**, **sin recargo por pedido pequeño**, sin umbral de envío gratis. Envío **0,99 €** en todas las franjas, del 28/09 al 31/12/2026, solo Madrid (dato del banner de la home; el importe por franja no se ha visto en ninguna captura).
6. Alcampo tiene un **WAF** (error 405 y CAPTCHA «Confirme que es humano»): hay que ir despacio (sección 9.2).
7. El emparejamiento automático solo es fiable en parte: lo dudoso se **pregunta al usuario** con el comando `confirmar`, y sus respuestas se guardan en `emparejamientos_alcampo.json` y se reutilizan.
8. **Historial de Carrefour:** disponible (39 pedidos con precio pagado por línea). **Historial de Lidl:** exportado (182 tickets). **Mercadona:** pendiente (falta su HAR). **Alcampo:** el usuario no compra allí, es solo comparación.
9. Lo que más pesó en el resultado fueron **pocas líneas dudosas** (pañuelos, papel higiénico, calabacín, cebolla): hay que revisar siempre las diferencias grandes antes de fiarse de una cifra.
10. El usuario trabaja en **Windows + PowerShell**, Python 3.14, Chrome. Código postal **28922** (Alcorcón, Madrid).
11. Siguiente paso recomendado: **repetir con otro pedido** (el del 04/09/2026, 200,88 €) para comprobar que el empate no es casualidad; después **Mercadona**.
12. Falta medir los **descuentos de cliente** de las dos cadenas (cheque ahorro de Carrefour, Club Alcampo) y las ofertas de cesta.

---

## 2. Contexto del usuario

- Vive en Alcorcón (Madrid), **CP 28922**. Tienda Carrefour usada: `005290`. Lidl cercano: «Alcorcón-Alcora Plaza».
- Hace la compra con otra persona (cesta común). Usa **Claude** (web, móvil y ahora Desktop) con conectores MCP propios.
- Windows, **PowerShell**, **Python 3.14**, **Chrome**. Su PC está encendido casi siempre.
- Condiciones de entrega de Carrefour **[Verificado]**: pedido mínimo a domicilio **50 €**, **envío gratis desde 140 €**, programa **Club Carrefour** con «cheque ahorro» (~1 %) y promociones de pedido del tipo «5 € de descuento gastando 140 €».
- Sus pedidos grandes de Carrefour rondan **140–200 €**.
- Las carpetas de trabajo están en `C:\Users\augus\Downloads` (el script busca `Downloads\MCP_Carrefour\historial_pedidos.json`).

---

## 3. Decisiones de arquitectura (y por qué)

| Decisión | Motivo |
|---|---|
| **Comparador separado del MCP de Carrefour** | El MCP de Carrefour escribe en el carrito real y depende de una sesión frágil. Mezclarlo acopla fallos y multiplica herramientas. |
| **Solo lectura y anónimo** | Precios, promos y stock son públicos. Sin sesión no hay fragilidad ni riesgo para sus cuentas. |
| **Un adaptador por cadena + librería común** | Cada web cambia por su cuenta; se aísla lo que se rompe. El núcleo (normalización y emparejamiento) se reutiliza. |
| **Historial propio como «cesta real»** | Es lo que lo diferencia de comparadores públicos: pone precio a *sus* compras reales. |
| **Script antes que MCP** | Se valida el método con un pedido real. Cuando esté estable se empaqueta como MCP (sección 7 del traspaso 1: 6–8 herramientas). |
| **El usuario decide lo dudoso** | Un motor de nombres nunca será perfecto con marcas blancas: lo dudoso se muestra con nombre completo, envase y precio, y se pregunta. |

Orden de cadenas: **Carrefour (hecho) → Alcampo (hecho para un pedido) → Mercadona → Lidl (historial y ofertas semanales)**. Dia, Eroski o Consum, más adelante.

---

## 4. Estado por cadena

### 4.1 Carrefour — búsqueda anónima **[Verificado]**
- `GET https://www.carrefour.es/search-api/query/v1/search` con: `internal=true, instance=x-carrefour, env=https://www.carrefour.es, scope=desktop, lang=es, session=empathy, catalog=food, citrusCatalog=food, baseUrlCitrus=https://www.carrefour.es, enabled=true, store=005290, hasConsent=false, siteKey=wFOzqveg, query=<texto>, start=0, rows=<n>, origin=search_box:none`.
- Hay que imitar a Chrome (**`curl_cffi` con `impersonate="chrome"`**); las peticiones normales las bloquea Cloudflare.
- Respuesta `content.docs[]`: `display_name`, `brand`, `active_price` (texto con punto), `strikethrough_price`, `price_per_unit_text`, `stock`, `catalog_ref_id`, `ean13`, `badge_map.promotions[...]`, `info_tags[...]`. `category_pim_code` viene vacío en alimentación.

### 4.2 Carrefour — historial de pedidos **[Verificado]**
Fichero local `historial_pedidos.json` (versión 2): `pedidos[{id,fecha,unidades,importe}]`, `detalle{id:{estado,fecha_pedido,totales{productos_sin_descuentos,descuentos_en_lineas,cheque_ahorro_usado,envio_pagado,total_final...},lineas[{nombre,ref,ean,cantidad,venta,precio_lista,precio_pagado,importe_sin_dto,importe,...}]}}`.
- **No comparar `precio_pagado` con precios de lista de otra cadena**: lo pagado incluye descuentos de pedido. Para comparar, usar `precio_lista`.
- Excluir pedidos reembolsados/rechazados/cancelados.
- Los nombres de línea de Carrefour incluyen el tamaño (`... 12 rollos.`, `... 24 ud.`, `pack de 3 latas de 52 g`): de ahí se sacan g/ml o unidades.

### 4.3 Alcampo — **comparación hecha**, herramienta `alcampo_comparar.py` v1.21

**API de búsqueda [Verificado]** (se llama desde el Chrome del usuario con un script de consola, o desde cualquier cliente que cumpla las cabeceras):
`GET https://www.compraonline.alcampo.es/api/webproductpagews/v6/product-pages/search?includeAdditionalPageInfo=true&maxPageSize=300&maxProductsToDecorate=50&q=<texto>&tag=web`
Cabeceras: `Accept: application/json; charset=utf-8`, `ecom-request-source: web`, `ecom-request-source-version: 2.0.0-2026-10-02-07h59m35s-c399fee2` (**fijada en el código: puede romperse cuando Alcampo actualice la web**), `client-route-id` y `page-view-id` (UUID aleatorios).
Producto (`productGroups[].decoratedProducts[]`): `retailerProductId`, `name`, `brand`, `packSizeDescription` (`"700ml"`, `"24 por envase"`), `price.amount`, `unitPrice`, `available`, `promotions[{type,description,requiredProductQuantity}]`, `categoryPath`.
- **Los nombres empiezan por la marca en MAYÚSCULAS** (`AUCHAN Queso rallado...`, `PRODUCTO ALCAMPO Alcaparras...`, `APEROL Licor...`). Los productos de marca blanca se anuncian como `PRODUCTO ALCAMPO` / `AUCHAN ... Producto Alcampo`.
- Sin iniciar sesión, la web cae por defecto en la zona **«Alcampo Vans Madrid Only»** («Envío a domicilio») con CP 28922: es la misma que ve el usuario, así que los precios son comparables.

**Cesta y condiciones [Verificado con HAR del usuario, cesta anónima de 20,84 €]:**
- `GET /api/cart/v1/carts/active`, `GET /api/cart/v2/carts/active/cart-view`, `POST /api/cart/v1/carts/active/apply-quantity`, `GET /api/ecomdeliverydestinations/v1/delivery-destinations/{id}/supported-propositions`.
- `minimumCheckoutThreshold = 0,01 EUR`, `smallOrderChargeThresholds = []`, `charges = {}`, `freeDeliveryProgress = HIDE_FREE_DELIVERY_PROGRESS`, única restricción `checkoutRestrictions = ["MISSING_SLOT"]` (falta elegir franja).
- Modalidades: `HOME_DELIVERY` programada (por defecto), `FAST` (<15 kg, no disponible en su zona), `CUSTOMER_COLLECTION` (recogida, disponible).
- **El coste de envío por franja NO salió en ninguna captura** (el usuario no llegó a elegir franja). El 0,99 € viene del **banner de la home** (`data-test="horizontal-advert"`, «ENVÍO 0,99€ en todas las franjas horarias. Exclusivo Madrid», del 28/09 al 31/12/2026). **[Sin verificar:]** si lleva condiciones (importe mínimo, primera compra).

**Promociones vistas en 1.114 productos (213 promos, 18 textos) [Verificado]:**
`[OFFER] Todo a 1€`, `2ª unidad -50% (fechas)`, `2ª unidad -70%`, `2ª und -50%. Solo Online`, `Descuento -15% (fechas)`, `Producto en Folleto`, `En pack, más fácil`, `Novedad Alcampo`; `[DELIVERY] Coste Servicio Gratis. Compra 20€ en selección de Unilever`; `[OFFER] 5€ dto. comprando 15€ en PepsiCo. Exclusivo Online`; `[LOYALTY] Club Alcampo 30% dto acumulado en tu tarjeta` / `Club Alcampo 2ª unidad -50% acum...`.
- El script aplica solo `2ª unidad -X %` / `2ª und` y `NxM` (3x2). **Excluye** todo lo de Club Alcampo (descuento de cliente acumulado en tarjeta), las ofertas de cesta y las de envío por marca.
- **[Sin verificar:]** si `Descuento -15 %` ya está dentro de `price.amount`.

**Lo que se aprendió operando con el WAF (sección 9.2):** ver abajo.

### 4.4 Lidl — historial **[Verificado]**, catálogo **[Verificado, de poco valor]**
(Sin cambios respecto al traspaso 1.)
- La web de Lidl no lista los básicos (la búsqueda «leche» no devuelve leche): el precio de Lidl se saca de los **tickets** del usuario.
- Tickets: `GET /mre/api/v1/tickets?country=ES&page=N` y `GET /mre/api/v1/tickets/{id}?country=ES&languageCode=es-ES` (`ticket.htmlPrintedReceipt`, texto de ancho fijo). Los anteriores a ~mayo de 2022 llegan sin detalle.
- Herramientas ya hechas: `lidl_exportar_tickets.js` (consola, descarga `lidl_tickets_AAAA-MM-DD.json`) y `lidl_tickets.py` v1.3 (acumula en `historial_lidl.json`).
- Resultado: 197 tickets (oct 2021–oct 2026), 182 con detalle, 2.892 líneas, gasto 7.634,72 €.
- Los nombres de Lidl van abreviados y sin tamaño: hace falta emparejamiento asistido.

### 4.5 Mercadona — **falta la captura HAR**
- Según fuentes externas **[Sin verificar]**: `tienda.mercadona.es` tiene API pública por código postal, sin login ni captcha, con precio de referencia por kg/l. Marca blanca: Hacendado. No deja historial de compras.
- Hace falta HAR de `tienda.mercadona.es` con el CP puesto (buscar ~5 productos y abrir uno).

---

## 5. Reglas de emparejamiento entre cadenas

Orden de confianza: **EAN idéntico** → **misma marca + mismo tamaño** → **mismo tipo + atributos + tamaño parecido** (marcas blancas: nunca idénticas; se compara el «equivalente más barato» y se marca como tal).

**Reglas del motor (traspaso 1, siguen vigentes):** tipo de producto = primera palabra significativa; se ignoran tamaños/unidades/marca blanca/conectores; atributos que no pueden cambiar (spray, congelado, fresco, bio, sin gluten, sin lactosa, vegano, integral, zero, light); estado (fresco/congelado/conserva); uso (repostería ≠ pizza ≠ rebozar); formato de envase compatible.

**Reglas añadidas en esta sesión (todas con casos reales de Alcampo):**
1. **Quitar el prefijo de marca en mayúsculas** del nombre de Alcampo antes de perfilar (conservando atributos como `ECOLÓGICO`).
2. **La cabeza del nombre no puede ser una palabra genérica** (`Original`, `Mini`...); se toma la primera no genérica.
3. **Marca de cabeza:** `Fanta de naranja Zero...` empareja con `FANTA ZERO Refresco de naranja...` porque la marca del candidato coincide con la primera palabra del original.
4. **Sinónimos de grafía:** `light`=`ligero`, `cubos`=`dados`, `biscottes`=`biscotes`.
5. **Formas de corte no cuentan como diferencia** (dados, rodajas, troceado, cortado, láminas, tiras, mitades, trozos), pero **si el original viene cortado, se prefiere el candidato cortado** (para no comparar cebolla en cubos con una malla de cebolla fresca de 2 kg). El usuario lo corrigió: «calabacín en dados o en rodajas es lo mismo».
6. **Calificadores que no pueden perderse en un equivalente estricto:** `oliva`, `virgen`, `girasol`, `desnatada`, `semidesnatada`, `entera`, `doble`, `triple`, `compact`, `gas` («agua con gas» no es «agua sin gas»; «aceite de oliva» no es «vegetal»; «doble rollo» no es rollo normal).
7. **Extras que convierten un producto en otro** (estricto los rechaza): `chocolate`, `cacao`, `caramelo`, `yogur`, `coco`, `miel`, `campero/camperas`, `gourmet` (tortitas de arroz ≠ tortitas con chocolate; huevos «frescos M» ≠ huevos camperas; altramuces Classic ≠ gran gourmet).
8. **Palabras de forma delante del tipo** (`Hojas de espinaca` = espinacas): protegidas con una lista.
9. **Tamaño:** se lee en g/ml (`pack de 3 latas de 52 g` = 156 g, `6 x 1 l`) y en **unidades** (`12 rollos`, `docena`, `40 por envase`, `pack de 6`).
   - **El precio de Alcampo se ajusta SIEMPRE al tamaño del original** (precio por unidad), incluso con diferencias pequeñas (1,5 l no cuesta lo que 1,25 l).
   - **Fiable solo entre 0,5× y 2×**, salvo **múltiplos exactos** (6 x 1 l frente a 1 l; ±3 %). Fuera de ese rango pasa a «a revisar».
10. **Elección entre candidatos:** primero estrictos, luego misma marca, luego en rango, luego **«completo»** (contiene todas las palabras del original, es decir, misma gama: así se prefiere `EVAX Cottonlike 32 uds` a `EVAX Fina y segura 16 uds`), luego corte, y por último **el más barato por envase del tamaño del original**.
11. **Rescates «laxos»** (van a «a revisar», NO a los totales, y se preguntan al usuario): misma marca aunque el tipo difiera (`Aperol` / `APEROL Licor...`); mismo tipo y tamaño parecido con ≤3 palabras de resto (alcohol etílico 96º / `Alcohol 96º`; edulcorante; biscotes; edamame). Respetan atributos y calificadores.
12. **Cobertura:** el informe separa **fiables** (entran en los totales), **a revisar** (laxas o sin tamaño comprobable; fuera de los totales) y **sin equivalente** (cuentan al precio de Carrefour en los dos lados para no sesgar).

---

## 6. Reglas para comparar cestas de forma justa

1. **Primero precio de estantería; después, con promociones.** Las promos dependen de la cantidad (3x2, 2ª unidad al 70 %).
2. **Incluir envío y mínimo** de cada cadena (por código postal y modalidad).
3. **Descuentos de cliente aparte** (cheque ahorro de Carrefour, Club Alcampo, Lidl Plus): no mezclar lo que ve cualquiera con lo que depende de ser cliente.
4. **Marcar la confianza de cada emparejamiento** y decir qué porcentaje del valor cubre la comparación.
5. **No comparar lo pagado con precios de lista.** Mostrar siempre **las dos cifras**: precio de lista y lo realmente pagado (con descuentos, cheque y envío).
6. Los precios cambian por semana y por zona: guardar **fecha y código postal** con cada precio.
7. **Antes de dar una cifra, revisar las «diferencias grandes» (±40 %)**: una sola línea mal emparejada movió el resultado 10 € en esta sesión (pañuelos de bambú frente a pañuelos normales).

---

## 7. Resultado del primer análisis (pedido Carrefour 13239790, 28/09/2026)

44 líneas; 83 % del valor emparejado de forma fiable (34 de 42 comparables; 10 confirmadas por el usuario); 2 a peso; 8 sin equivalente.

| | Importe |
|---|---|
| Carrefour, precio de lista (cesta completa) | 146,46 € |
| Alcampo, estimación a precio de estantería | 138,55 € (−5,4 %) |
| Alcampo + envío 0,99 € | **139,54 €** |
| Lo que el usuario pagó en Carrefour (con descuentos, cheque ahorro 3,68 € y envío gratis) | 137,78 € |
| …sin contar el cheque ahorro | 141,46 € |

- Sobre lo emparejado: Alcampo −6,7 % (110,64 € frente a 118,55 €).
- Alcampo más barato en: papel higiénico (si «doble rollo» no cuenta doble), vinagre balsámico, alcaparras, tomates secos, Chocolinas, Aperol, atún en pack de 6, compresas Evax.
- Carrefour más barato en: altramuces, Babybel, calabacín, agua con gas, pimientos de Padrón.
- **Sin equivalente (decisión del usuario):** queso azul, tortitas de arroz Bicentury, crema Vulpi, huevos (Alcampo solo trae camperas), sopa Gallina Blanca (71 g), pañuelos Deco, biscotes, jabón de manos.
- **Puntos débiles:** el papel higiénico vale 2,69 € si «doble rollo» no cuenta doble y ~5,40 € si cuenta (±2,7 €); el 17 % del valor cuenta a precio de Carrefour en los dos lados; Club Alcampo y ofertas de cesta no medidos; la promoción de envío acaba el 31/12/2026; es un solo pedido de una sola semana.
- **Conclusión:** empate técnico en coste real; Alcampo mejor en compras pequeñas (sin mínimo, envío 0,99 €) y en precio de estantería; Carrefour recupera con sus descuentos y el envío gratis desde 140 €.

---

## 8. Plan por fases y siguiente paso

1. Librería común + adaptador Carrefour (búsqueda anónima + historial): **hecho** (en el script; el MCP de Carrefour del usuario sigue aparte).
2. Adaptador Alcampo + comparación Carrefour→Alcampo: **hecho** (script v1.21, un pedido).
3. **← Siguiente (recomendado): repetir con otro pedido** (04/09/2026, 200,88 €, ver 8.1) para comprobar que el empate se mantiene.
4. Adaptador **Mercadona** (con su HAR).
5. **Lidl:** historial de tickets como fuente de precios reales + ofertas semanales opcionales. Emparejamiento asistido con ~40 productos.
6. Medir **descuentos de cliente** (Club Alcampo, cheque ahorro) y ofertas de cesta, y mostrarlos aparte.
7. Historial unificado de las tres cadenas («qué comprar dónde»).
8. Empaquetar como **MCP comparador** (6–8 herramientas, ver traspaso 1 §7) cuando el método esté estable.
9. Dia/Eroski/Consum si interesa.

### 8.1 Cómo repetir con otro pedido (sin Claude Code en la nube)
1. `python alcampo_comparar.py consultas --pedido <ID>` → genera `alcampo_exportar_listo.js`.
2. Chrome en `compraonline.alcampo.es` (CP 28922), F12 → Consola → pegar el contenido del `.js` (si pide, escribir `allow pasting`). **Respetar las normas anti-WAF de 9.2.**
3. Se descarga `alcampo_resultados.json`; si ya existe, Chrome añade `(1)`, `(2)`... y el script **los fusiona todos**.
4. `python alcampo_comparar.py consultas --pedido <ID> --faltan` para completar lo que falte; `--sin-equivalente` para búsquedas cortas de rescate (marca / primera palabra).
5. `python alcampo_comparar.py confirmar --pedido <ID>` (y `--grandes` para volver a preguntar las diferencias de ±40 %).
6. `python alcampo_comparar.py comparar --pedido <ID>`.

---

## 9. Métodos

### 9.1 Análisis de un HAR (el que funcionó con Carrefour, Lidl y Alcampo)
1. **Inventario de endpoints:** filtrar estáticos y analítica; agrupar por método+ruta; mirar tamaños. (En el HAR de Alcampo: 112 peticiones al dominio, 10 rutas de API relevantes.)
2. Los cuerpos pueden venir en **base64** (`response.content.encoding == "base64"`).
3. Si un producto conocido no sale en ninguna API JSON, buscarlo en el HTML (Nuxt `__NUXT_DATA__` con devalue, `window.__INITIAL_STATE__`, JSON-LD).
4. **Imprimir estructura, no datos**; ocultar claves personales (nombre, email, teléfono, dirección, tokens, ids de cliente).
5. Comprobar cabeceras (el HAR suele quitar cookies/Authorization).
6. Escribir el parser con el HAR como material de prueba y comprobar que las cuentas cuadran.
7. **Avisar al usuario de que su HAR puede contener tokens y datos personales y que debe borrarlo después.** (Los HAR de Lidl y de Alcampo incluían identificadores de sesión.)

### 9.2 Operar con el WAF de Alcampo (normas aprendidas)
- **Ritmo:** con una búsqueda cada 0,45 s, a las ~40 peticiones empezaron los **405 (Method Not Allowed)** en todas. Con **una cada 1,5–2,5 s** (v1.2+) pasaron 31/31 sin problema.
- Tras el bloqueo, Chrome mostró la pantalla **«Confirme que es humano»** (CAPTCHA). **Lo resuelve el usuario a mano. No se automatiza ni se elude.** Después, esperar **15–20 minutos** antes de lanzar más búsquedas y navegar un poco a mano.
- El script de consola **se detiene solo tras 3 fallos seguidos** y descarga lo conseguido (`"incompleto": true`).
- **Truco para no perder lo que ya hay en una pestaña bloqueada:** en la misma consola, `window.fetch = async () => new Response("", {status: 400});` hace fallar rápido las búsquedas que quedan, el script termina y descarga `alcampo_resultados.json` con lo conseguido. Luego recargar la página (F5).
- **Si el entorno de Claude puede acceder a la web** (en Claude Code en la nube hubo que permitir el dominio en la política de red): `curl` con las cabeceras de 4.3 respondió 200 sin CAPTCHA a unas 15 consultas espaciadas 3 s. Chromium con Playwright no pudo usarse (faltaba `certutil` para confiar en la CA del proxy). **En Claude Desktop esto no aplica**: las búsquedas se hacen desde el Chrome del usuario.
- Ojo: la cabecera `ecom-request-source-version` está fija en el JS; si Alcampo actualiza la web puede dejar de funcionar y habrá que leer la versión nueva del HAR.

---

## 10. Normas de trabajo con este usuario (aprendidas durante el proyecto)

- **Idioma:** español de España, tú/vosotros. **Nunca** voseo ni «che/vos/dale».
- **Cambios de código: fichero completo adjunto para reemplazar**, nunca «edita la línea X». No pegar código largo en el chat.
- **Pasos prácticos y numerados**; cada paso necesario (recargar, reiniciar, copiar el fichero) como paso propio.
- **Comandos de PowerShell en una sola línea**; sin bloques «here-string». Poner siempre ejemplos con el nombre real de los ficheros.
- **Conclusiones como hechos solo cuando están verificadas**; separar siempre lo verificado de lo supuesto. Corregirse sin rodeos si se detecta un error.
- **Probar antes de entregar**, con las capturas reales como material de prueba y con pruebas automáticas. Entregar solo lo que pasa.
- **Respuestas breves y accionables.** Pedir salidas cortas (informes), no ficheros enteros con sus compras.
- **Privacidad:** no pedir contraseñas; no repetir tokens, tarjetas ni datos personales. El pago **nunca** se automatiza.
- **Nuevo, aprendido hoy (el usuario lo corrigió varias veces):**
  1. **No preguntar lo que los datos ya muestran.** Antes de pedirle algo, mirar el informe: los «24 huevos» ya salían en el nombre; el tamaño del vinagre estaba en los datos y el informe lo ocultaba (se cortaba el nombre). Los informes deben mostrar **nombre completo, envase y precio** de cada pareja.
  2. **Investigar antes de probar a ciegas:** ante «sin equivalente», mirar qué devuelve realmente la web de Alcampo (había casi todo con otro nombre) en vez de lanzar más búsquedas.
  3. **No dar una cifra definitiva si depende de pocas líneas dudosas.** Decir cuáles son y cuánto mueven el total. Cuando un cambio de reglas dio la vuelta al resultado (Alcampo −9,6 % → +2,8 % → −5,4 %), el motivo estaba en 2–3 líneas.
  4. **Sentido común del consumidor:** calabacín en dados o en rodajas es lo mismo; en el peor caso no se descarta, se marca «casi equivalente» y se pregunta.
  5. **Mirar todo lo público, no solo lo que se espera:** el envío a 0,99 € estaba en un banner de la home que se había descargado y no se había buscado bien. Usar el HAR/la web del usuario antes de suponer un valor.

---

## 11. Riesgos y avisos

- **Condiciones de uso:** acceso **no oficial**. Uso personal, pocas peticiones, pausas largas, **parar si hay bloqueo**; no saltarse protecciones (CAPTCHA, WAF).
- **Las webs cambian:** adaptador por cadena, pruebas con capturas guardadas y mensajes claros de «esta tienda no responde ahora».
- **Comparar con precios de lista, no pagados**, y avisar siempre de qué porción de la cesta se ha emparejado.
- **La promoción de envío de Alcampo (0,99 €) acaba el 31/12/2026**; la zona «Madrid Only» puede cambiar.
- **El emparejamiento por nombres nunca será perfecto**: revisar las «diferencias grandes» y confirmar lo dudoso.
- **HAR con datos de sesión:** borrar siempre tras analizarlos.

---

## 12. Inventario de ficheros (en el PC del usuario, carpeta `Descargas`)

| Fichero | Para qué sirve |
|---|---|
| `alcampo_comparar.py` (**v1.21**) | Compara un pedido de Carrefour con Alcampo. **Adjuntarlo en la sesión nueva.** Comandos: `consultas` (`--pedido`, `--faltan`, `--sin-equivalente`), `comparar` (`--pedido`, `--envio-alcampo`, por defecto 0,99), `diagnostico` (`--lineas`), `confirmar` (`--grandes`). |
| `alcampo_exportar_listo.js` | Script de consola con las búsquedas del pedido dentro (se regenera con `consultas`). |
| `alcampo_resultados.json`, `alcampo_resultados (1).json`, `(2)` | Precios de Alcampo del 04/10/2026 (zona «Alcampo Vans Madrid Only»). El script los fusiona. **Conservar.** |
| `emparejamientos_alcampo.json` | **Las respuestas del usuario** (sí/no) a `confirmar`, por producto de Carrefour. Se reutilizan en otros pedidos. **Conservar.** |
| `comparacion_alcampo.json` | Detalle completo de la última comparación. |
| `MCP_Carrefour\historial_pedidos.json` | Historial de pedidos de Carrefour (fuente de la «cesta real»). |
| `MCP_Carrefour\carrefour_es_mcp.py` (v2.8) | MCP de Carrefour (carrito, pedidos…). No hace falta para este proyecto, salvo como referencia. |
| `lidl_exportar_tickets.js`, `lidl_tickets.py` (v1.3), `historial_lidl.json`, `lidl_tickets_2026-10-04.json` | Herramientas y datos de Lidl (sección 4.4). La copia `lidl_tickets_2026-10-04.json` es la **copia de seguridad completa**: no borrar. |
| (borrar) HAR de Alcampo/Lidl | Contienen datos de sesión: borrarlos tras usarlos. |

Respaldo del script en GitHub: repo `apaolini137/comparador-supermercados`, rama `claude/new-session-wiux5c` (el usuario ha dicho que el repo no le preocupa; es solo una copia).

Para continuar en una conversación nueva basta con este documento, `alcampo_comparar.py` y, si hace falta una prueba con datos reales, `historial_pedidos.json` o `historial_lidl.json`. **No subir** ni pegar nunca ficheros con tokens.
