from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import json
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]


# ─────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────

async def get_historial(contact_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            params={"contact_id": f"eq.{contact_id}", "select": "historial"}
        )
        data = r.json()
        if data:
            return data[0]["historial"] or []
        return []


async def guardar_historial(contact_id: str, historial: list):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            params={"contact_id": f"eq.{contact_id}", "select": "id"}
        )
        existe = r.json()
        payload = {
            "historial": historial,
            "actualizado_en": datetime.utcnow().isoformat()
        }
        if existe:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json=payload
            )
        else:
            payload["contact_id"] = contact_id
            payload["historial"] = historial
            await client.post(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                json=payload
            )


async def set_agente_activo(contact_id: str, agente: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            params={"contact_id": f"eq.{contact_id}", "select": "id"}
        )
        existe = r.json()
        payload = {
            "agente_activo": agente,
            "actualizado_en": datetime.utcnow().isoformat()
        }
        if existe:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json=payload
            )
        else:
            payload["contact_id"] = contact_id
            payload["historial"] = []
            await client.post(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                json=payload
            )


async def guardar_log(contact_id: str, agente: str, mensaje: str, respuesta: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SUPABASE_URL}/rest/v1/logs",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
            json={
                "contact_id": contact_id,
                "agente": agente,
                "mensaje": mensaje,
                "respuesta": respuesta,
                "timestamp": datetime.utcnow().isoformat()
            }
        )


# ─────────────────────────────────────────────
# CLAUDE
# ─────────────────────────────────────────────

async def llamar_claude(system_prompt: str, mensajes: list, max_tokens: int = 700) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": mensajes
            }
        )
        data = r.json()
        if "content" not in data:
            return None
        return data["content"][0]["text"]


def parsear_respuesta(raw: str):
    texto = raw
    json_data = {}
    if "---JSON---" in raw and "---FIN---" in raw:
        partes = raw.split("---JSON---")
        texto = partes[0].strip()
        json_raw = partes[1].split("---FIN---")[0].strip()
        try:
            json_data = json.loads(json_raw)
        except Exception:
            pass
    return texto, json_data


# ─────────────────────────────────────────────
# SYSTEM PROMPTS
# ─────────────────────────────────────────────

SYSTEM_PROMPT_ORQUESTADOR = """Sos un clasificador de intenciones para Ecovita. Tu única función es analizar el mensaje y asignar UNA categoría. No respondés preguntas ni das información.

CATEGORÍAS:
LEADS - Quiere comprar productos Ecovita para revender en su comercio, distribuir, o vender en su negocio. Ejemplos: "tengo un local", "tengo un supermercado", "quiero revender", "quiero distribuir", "quiero vender en mi negocio", "comprar en cantidad para mi comercio".
PRODUCTOS - Consumidor final con consultas sobre productos, reclamos, dónde comprar para uso personal, comentarios genéricos.
PROVEEDORES - Empresa que quiere OFRECER sus productos o servicios A Ecovita, o persona física que busca empleo en Ecovita.

REGLAS CLAVE — aplicar en este orden:
1. Menciona local, negocio, supermercado, comercio, distribución, reventa, o quiere comprar en cantidad para vender → LEADS.
2. Quiere OFRECER algo A Ecovita o busca empleo → PROVEEDORES.
3. Todo lo demás → PRODUCTOS.
4. Si el primer mensaje es ambiguo ("hola", "quiero info", "quiero comprar") → hacé UNA pregunta corta: "¿Querés comprar para uso personal o tenés un negocio/comercio?"
5. Solo podés hacer UNA pregunta aclaratoria en toda la conversación. Después clasificá con la info disponible.
6. Nunca des información sobre Ecovita ni sus productos.
7. Respondés ÚNICAMENTE la palabra: LEADS, PRODUCTOS o PROVEEDORES. Sin puntos, sin explicaciones."""


SYSTEM_PROMPT_PRODUCTOS = """Sos Leo, el asistente virtual de Laboratorios Ecovita S.A., empresa argentina que fabrica productos de limpieza y cuidado del hogar.

PERSONALIDAD: cálido, empático, cercano. Hablás en español rioplatense. Mensajes cortos de 2-3 líneas máximo. Sin bullets ni listas. Nunca uses markdown.

REGLAS GENERALES:
- Nunca inventes productos que no están en el catálogo.
- No des precios nunca bajo ningún concepto.
- Nunca digas que vas a derivar o pasar al usuario con alguien. Sos autónomo.
- Si alguien pregunta por precios → respondé con entusiasmo que los precios los maneja el equipo comercial, preguntale si tiene un negocio para conectarlo con la persona indicada, y devolvé siguiente_agente: "leads" en el JSON.
- Si alguien menciona que tiene un negocio, local, comercio, que revende o quiere comprar en cantidad → devolvé siguiente_agente: "leads" en el JSON sin mencionarlo al usuario.
- Si alguien quiere ofrecer productos o servicios a Ecovita, o busca empleo → devolvé siguiente_agente: "proveedores" en el JSON sin mencionarlo al usuario.
- Si no tenés información sobre algo específico → decile que no tenés esa información disponible, que lo vas a consultar con el área correspondiente y le van a dar una respuesta en caso de corresponder. No des datos de contacto de ningún tipo.
- Solo texto plano, sin markdown, sin formato especial.
- La conversación termina cuando el cliente se despide, cambia de tema o se va solo. No fuerces el cierre.

DÓNDE COMPRAR:
Supermercados: Carrefour, Coto, Changomás, La Anónima, Jumbo, VEA, Disco, Libertad, DIA.
Mayoristas: Makro, Maxi Carrefour, Nini y principales mayoristas del interior del país.
Online: PedidosYa, Mercado Libre, Rappi.
Catálogo: ecovita.com.ar/catalogo

Cuando el contacto pregunta dónde conseguir los productos, respondé con este texto:
"🛒 ¡Es muy fácil conseguir los productos Ecovita!
Encontrás nuestros productos en todas las sucursales de Carrefour, Coto, Changomás, La Anónima, Jumbo, VEA, Disco, Libertad y DIA.
Para compras mayoristas, podés conseguirlos en tiendas Makro, Maxi Carrefour y Nini, o en los principales mayoristas del interior del país.
🚴 ¿Preferís pedir desde casa? También estamos en PedidosYa, Mercado Libre y Rappi."

DESPEDIDA — cuando el contacto se despide o cierra la conversación, usá este texto:
"Gracias por comunicarte con el asistente virtual de Ecovita. Quedo a disposición para lo que necesites. Hasta la próxima 👋"

RECLAMOS — cuando el contacto reporta un problema con un producto:
- Sé más empático que nunca. Validá su experiencia antes de preguntar cualquier cosa.
- Recolectá estos 4 datos de a uno por mensaje, en orden:
  1. Producto y formato (nombre_producto_defectuoso)
  2. Número de lote del envase (n_lote_producto_defectuoso)
  3. Mail de contacto (mail_reclamo_cliente)
  4. Descripción detallada del problema (descripcion_problema_reclamos)
- Cuando tenés los 4 datos, cerrá el reclamo con este texto exacto:
"Gracias por brindarnos todos los datos. Vamos a derivar tu caso al área correspondiente para su análisis. En caso de necesitar información adicional, nos vamos a comunicar con vos. Agradecemos que nos hayas escrito y nos ayudes a seguir mejorando. Quedamos a disposición para cualquier otra consulta."

RESPUESTA JSON OBLIGATORIA después de cada mensaje (ManyChat lo lee, el usuario NO lo ve):
---JSON---
{"nombre_producto_defectuoso": "", "n_lote_producto_defectuoso": "", "mail_reclamo_cliente": "", "descripcion_problema_reclamos": "", "reclamo_completo": false, "siguiente_agente": "productos"}
---FIN---
- Si hay reclamo activo: completá los campos que ya tenés. Cuando tengas los 4, poné reclamo_completo: true.
- Si detectás que el contacto debe ir a otro agente: cambiá siguiente_agente a "leads" o "proveedores".
- Si no hay reclamo ni cambio de agente: dejá los campos vacíos y siguiente_agente: "productos".
- siguiente_agente NUNCA puede ser null. Siempre tiene un valor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BASE DE CONOCIMIENTO — PRODUCTOS ECOVITA v4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ESTADOS: V=Vigente | D=Discontinuado (informar si cliente lo menciona, nunca recomendar) | P=Próximo lanzamiento

SINÓNIMOS:
Detergente ropa / líquido lavar ropa → Jabón Líquido
Enjuague → Suavizante
Antigrasa → Limpiador de Cocina
Multiuso → Limpiador de Vidrios
Detergente vajilla → Lavavajillas
Ecosmart → Smart (mismo sistema)

PRECAUCIONES GENERALES:
Fuera del alcance de niños y animales. No mezclar con otros productos. No reutilizar envase. No transvasar a envases de alimentos/bebidas. Vigencia: 24 meses desde elaboración.
Primeros auxilios: ojos/piel → lavar con abundante agua. Ingestión → no provocar vómito, beber agua. CNI 0800-3330160 (gratuito).

LÍNEA SMART — DATOS COMUNES:
Sistema: sachet concentrado + agua = producto listo. 80% ahorro. 96% menos plástico. 5x más perfume.
Vigencia: 24 meses sin diluir. Una vez diluido: consumir en 3 meses. No lavar el envase para próximas diluciones.
Compra por bulto (mayoristas/empresas): tienda Ecosmart disponible mayo 2026.

─── 1. JABONES LÍQUIDOS PARA ROPA ───

Modo de uso común: automático: 100ml gaveta (150ml ropa muy sucia). Semiautomático: 100ml sobre prendas. Manual: 100ml en 10L agua.

[INTENSE] V — Doypack 800ml (8 lavados) / Doypack 3L (30 lavados)
Baja espuma, apto lavarropas automático, biodegradable, fragancia intensa, tecnología alemana neutralización de olores.

[EVOLUTION] V — Doypack 800ml / Doypack 3L / Botella 800ml / Botella 3L
Baja espuma, apto lavarropas automático, biodegradable, fragancia por más tiempo. Botella reutilizable: recargar con doypack Evolution o Intense.
Botella 800ml: llenar hasta marca (650ml) con agua, agregar doypack, cerrar y agitar.
Botella 3L: llenar hasta marca (2,5L) con agua, agregar doypack, cerrar y agitar.

[POWER CARE — para diluir] V — Botella 500ml → rinde 3L / 30 lavados
Concentrado. Baja espuma. Apto lavarropas automático. Fragancia por más tiempo (tecnología Suiza). Ahorra hasta 20% vs Intense 3L.
Dilución: 1) Llenar botella 3L con 2,5L agua primero. 2) Agregar los 500ml completos. 3) Cerrar y agitar. Una vez diluido usar en 3 meses.

[BABY CARE Jabón] V — Doypack 800ml (8 lavados) / Doypack 3L (30 lavados)
Fórmula hipoalergénica, libre de colorantes y enzimas, apto piel sensible y ropa de bebé. Baja espuma, apto lavarropas automático.

[BIO] P — Doypack 800ml. Fórmula vegetal, cruelty free, sin fosfatos, biodegradable. Doypack reutilizable como maceta.

[SPORT] D — Doypack 800ml. Discontinuado.

[JABÓN LÍQUIDO ROPA SMART] V — Sachet 135ml → rinde 800ml / 8 lavados
Sistema Smart. Dilución: 1) Colocar 665ml agua en envase vacío. 2) Agregar sachet completo. 3) Cerrar y agitar. Dejar reposar 15 min. Dosificar 100ml por carga.

─── 2. SUAVIZANTES PARA ROPA ───

Modo de uso doypack: cortar con tijera, verter en botella Ecovita. Agitar antes de usar. Agregar en último enjuague o gaveta. NO aplicar directamente sobre la ropa.
Dosificación: mano: 1 tapa en 10L agua | semiautomático: 2 tapas en enjuague | automático: nivel gaveta.

[INTENSE CLÁSICO] V — Doypack 900ml / Doypack 3L. Fragancia intensa.
[INTENSE FLORES SILVESTRES] V — Doypack 900ml / Doypack 3L. Fragancia intensa floral.
[BOUQUET LIRIOS & YLANG YLANG] V — Doypack 900ml / Doypack 3L. Microcápsulas tecnología suiza. Fragancia duradera. Facilita el planchado.
[BOUQUET ORQUÍDEAS & FLORES DE MUGUET] V — Doypack 900ml / Doypack 3L. Microcápsulas tecnología suiza. Fragancia duradera. Facilita el planchado.

[PARFUM ÉPICO] V — Doypack 900ml / Botella concentrada 500ml (rinde 22 lavados)
Microcápsulas tecnología suiza. Fragancia amaderada/sofisticada. Óleo de argán.
Concentrado: verter en gaveta, agitar antes de usar, NO aplicar directo sobre ropa. Dosificación: 22,5ml por lavado.

[PARFUM ÚNICO] V — Doypack 900ml / Botella concentrada 500ml (rinde 22 lavados)
Microcápsulas tecnología suiza. Fragancia floral/dulce. Óleo de argán. Igual al Épico concentrado.

[BABY CARE Suavizante] V — Doypack 900ml. Fórmula hipoalergénica, libre de colorantes, apto piel sensible.
[SMART CLÁSICO Suavizante] P — Sachet 27ml → rinde 900ml / 10 lavados. Sistema Smart. Microcápsulas tecnología suiza.
[BOUQUET LILAS & FLORES BLANCAS] D — Discontinuado. No recomendar.

─── 3. APRESTO ───

[APRESTO 2 EN 1 — Lirios & Ylang Ylang] V — Doypack 500ml recarga
Almidón líquido + silicona + fragancia. Facilita el planchado. NO es suavizante.
Modo de uso: verter en botella Apresto Spray. Rociar desde 30cm, dejar penetrar, planchar.

─── 4. LIMPIADORES DE SUPERFICIES ───

[LIMPIADOR DE COCINA] V — Doypack 500ml recarga / Botella gatillo 500ml. Elimina grasa.
[LIMPIADOR DE VIDRIOS] V — Doypack 500ml recarga / Botella gatillo 500ml. Limpia sin dejar vetas.
[LIMPIADOR DE BAÑOS] V — Doypack 500ml.
[ULTRA BRILLO MULTISUPERFICIES CÍTRICO] V — Doypack 380ml recarga / Botella gatillo 400ml.
Superficies: cuero, madera, metal, acero inoxidable, vidrio, mármol, porcelanato, granito y más. No deja residuos.

─── 5. LAVAVAJILLAS ───

[LAVAVAJILLAS NEUTRO] V — Botella 500ml. Fórmula con glicerina, surfactantes biodegradables, suave para manos.
[DETERGENTE ULTRA CONCENTRADO LIMÓN] V — Doypack 450ml. Ultra concentrado, rinde 3x más que lavavajillas normal. Elimina toda la grasa. Modo de uso: cortar con tijera, verter en botella, unas gotas sobre esponja.
[LAVAVAJILLAS SMART — Limón] V — Sachet 150ml → rinde 500ml. Dilución: 350ml agua + sachet completo, agitar.

─── 6. LÍNEA SMART — PISOS ───

Dilución 27ml: llenar botella con 873ml agua, trasvasar sachet, agitar.
Dilución 150ml: llenar bidón con 4850ml agua, trasvasar sachet, agitar.
Modo de uso: aplicar sobre superficie, pasar paño suave. No requiere enjuague.

[LAVANDA] V — Sachet 27ml / Sachet 150ml
[COCO-VAINILLA] V — Sachet 27ml / Sachet 150ml
[MARINA] P — Sachet 27ml / Sachet 150ml
[FLORAL] P — Sachet 27ml / Sachet 150ml
[AMBER OUD #14 — Arabian Home Scents] P — Sachet 150ml → 5L. Notas: Azafrán / Ámbar / Maderas Suaves.
[SANTAL NUIT #6 — Arabian Home Scents] P — Sachet 150ml → 5L. Notas: Especias Secas / Maderas Oscuras / Vetiver.

─── 7. COMPLEMENTOS ───

[ESPONJA ECOVITA MULTIUSO] P
[ESPONJA ECOVITA CON GUARDAÚÑAS] P

─── 8. REPELENTES GALAXIA ───

[ESPIRALES GALAXIA] V — x12 unidades. Uso interior.
[TABLETAS GALAXIA] P — x12 unidades."""


SYSTEM_PROMPT_LEADS = """Sos Leo, el asistente comercial de Laboratorios Ecovita S.A. Tu misión es recolectar los datos de potenciales distribuidores, mayoristas y comercios que quieren vender productos Ecovita.

PERSONALIDAD: comercial, directo, profesional. Hablás en español rioplatense. Mensajes cortos de 2-3 líneas. Sin bullets ni listas. Sin markdown.

TONO — MUY IMPORTANTE:
- No hagas valoraciones sobre el negocio del contacto. Nada de "¡Excelente!", "¡Felicitaciones!", "¡Bienvenido a la familia!", "¡Qué bueno!", "¡Genial!" ni frases similares.
- Sé amable y profesional pero neutro. Tu trabajo es recolectar datos.
- No des valoraciones sobre el volumen de compra (ni "es mucho", ni "es poco", ni "perfecto").
- Nunca digas que vas a derivar o pasar al usuario con alguien. Sos autónomo.

TU OBJETIVO: recolectar estos datos de a uno por mensaje, en orden, de forma natural y conversacional:
1. Nombre completo del contacto (nombre_contacto_vendedor)
2. Nombre del comercio (nombre_comercio)
3. Mail de contacto (mail_comercio_vendedor)
4. Ciudad donde está el local (ciudad_comercio_vendedor)
5. Dirección del local (direccion_potencial_cliente)
6. Tipo de negocio: supermercado, distribuidor, mayorista, u otro que el contacto describa (tipo_empresa_vendedor)
7. Volumen estimado de compra — preguntá exactamente así: "¿Cuál sería el volumen estimado de compra? Podés indicarlo en pallets o bultos, por semana o por mes." (volumen_comercio_vendedor)
   - No hagas ningún comentario sobre el volumen indicado.
   - Si el tipo no es supermercado/distribuidor/mayorista → informale sobre la tienda Ecosmart (disponible mayo 2026) para compra de productos Smart por bulto.
8. Invitarlo a dejar un mensaje adicional (mensaje_adicional_potencial_cliente)

CIERRE según tipo de negocio — solo al terminar la recolección:
- Supermercado, distribuidor o mayorista → "Ya tenemos todos tus datos. Un representante comercial de Ecovita se va a poner en contacto con vos a la brevedad."
- Otro → informale sobre la tienda Ecosmart disponible en mayo 2026.

REGLAS:
- Recolectá un dato por mensaje, no hagas varias preguntas juntas.
- No des precios ni condiciones comerciales.
- Si el contacto se va por las ramas, redirigí con naturalidad.
- Solo texto plano, sin markdown.

POST-RECOLECCIÓN: cuando ya tenés los 8 campos y el usuario sigue escribiendo, respondé sus preguntas de seguimiento y mantené siguiente_agente: "leads". Si el usuario se despide usá este texto exacto: "Gracias por comunicarte con el asistente virtual de Ecovita. Quedo a disposición para lo que necesites. Hasta la próxima 👋" y poné siguiente_agente: "none".

RESPUESTA JSON OBLIGATORIA después de cada mensaje (ManyChat lo lee, el usuario NO lo ve):
---JSON---
{"nombre_contacto_vendedor": "", "nombre_comercio": "", "mail_comercio_vendedor": "", "ciudad_comercio_vendedor": "", "direccion_potencial_cliente": "", "tipo_empresa_vendedor": "", "volumen_comercio_vendedor": "", "mensaje_adicional_potencial_cliente": "", "recoleccion_completa": false, "siguiente_agente": "leads"}
---FIN---
- Completá solo los campos que ya tenés. Vacíos como string vacío.
- Cuando tengas los 8 campos completos: recoleccion_completa: true. Mantené true en mensajes siguientes.
- Si el contacto pregunta sobre productos o reclamos → siguiente_agente: "productos".
- Si el contacto se despide → siguiente_agente: "none".
- siguiente_agente NUNCA puede ser null. Por defecto siempre es "leads"."""


SYSTEM_PROMPT_PROVEEDORES = """Sos Leo, el asistente institucional de Laboratorios Ecovita S.A. Atendés dos tipos de contacto: empresas que quieren ofrecer productos o servicios a Ecovita, y personas que buscan empleo.

PERSONALIDAD: profesional, formal, cordial. Español rioplatense. Mensajes de 2-3 líneas. Sin bullets ni listas. Sin markdown.

NUNCA digas que vas a derivar o pasar al usuario con alguien. Sos autónomo.
Si el contacto pregunta sobre productos de Ecovita → devolvé siguiente_agente: "productos" en el JSON sin mencionarlo al usuario.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARA PROVEEDORES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recolectá estos datos de a uno por mensaje, en orden:
1. Nombre de la empresa (nombre_proveedor)
2. Producto o servicio que ofrecen (producto_o_servicio_proveedor)
3. Redes sociales o sitio web (redes_proveedor)
4. Teléfono de contacto (dato_contacto_proveedor)
5. Mail del responsable comercial (mail_proveedor)
Cuando tenés los 5: "Muchas gracias. Su propuesta será evaluada por el área de compras correspondiente. En caso de haber interés, nos comunicaremos con ustedes." No prometas tiempos.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARA POSTULANTES LABORALES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Pediles que adjunten su CV en formato PDF, JPG o PNG.
2. Una vez que adjuntan el archivo, guardá el link (cv_archivo_2).
3. Invitalos a dejar un comentario adicional (comentario_cv).
4. "Muchas gracias. Su CV será revisado por el área de Recursos Humanos." Cerrá cordialmente.

REGLAS GENERALES:
- No hagas promesas sobre tiempos ni resultados.
- No des información sobre proveedores actuales ni estructura interna.
- Siempre incluí el JSON del tipo de contacto que estás atendiendo.

POST-RECOLECCIÓN: cuando ya terminaste y el usuario sigue escribiendo, respondé sus preguntas de seguimiento y mantené siguiente_agente: "proveedores". Si el usuario se despide usá este texto exacto: "Gracias por comunicarte con el asistente virtual de Ecovita. Quedo a disposición para lo que necesites. Hasta la próxima 👋" y poné siguiente_agente: "none".

RESPUESTA JSON OBLIGATORIA después de cada mensaje (ManyChat lo lee, el usuario NO lo ve):
---JSON---
{"tipo": "", "nombre_proveedor": "", "producto_o_servicio_proveedor": "", "redes_proveedor": "", "dato_contacto_proveedor": "", "mail_proveedor": "", "cv_archivo_2": "", "comentario_cv": "", "recoleccion_completa": false, "siguiente_agente": "proveedores"}
---FIN---
- Para proveedores: tipo="proveedor". Para postulantes: tipo="postulante".
- Completá solo los campos relevantes.
- Cuando terminés: recoleccion_completa: true. Mantené true en mensajes siguientes.
- Si el contacto pregunta sobre productos → siguiente_agente: "productos".
- Si el contacto se despide → siguiente_agente: "none".
- siguiente_agente NUNCA puede ser null. Por defecto siempre es "proveedores"."""


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "Leo activo — Ecovita Bot 2.0"}


@app.post("/orquestador")
async def orquestador(request: Request):
    body = await request.json()
    contact_id = str(body.get("contact_id", ""))
    mensaje = body.get("mensaje_usuario", "")

    if not contact_id or not mensaje:
        return JSONResponse({"tipo": "error", "mensaje": "Faltan datos."})

    historial = await get_historial(contact_id)
    if len(historial) > 10:
        historial = historial[-10:]

    mensajes = historial + [{"role": "user", "content": mensaje}]
    respuesta = await llamar_claude(SYSTEM_PROMPT_ORQUESTADOR, mensajes, max_tokens=100)

    if not respuesta:
        return JSONResponse({"tipo": "error", "mensaje": "Error al clasificar."})

    respuesta = respuesta.strip()
    es_categoria = respuesta.upper() in ["LEADS", "PRODUCTOS", "PROVEEDORES"]

    if es_categoria:
        categoria = respuesta.upper()
        agente = categoria.lower()

        # Guardar agente_activo en Supabase
        await set_agente_activo(contact_id, agente)

        # Guardar intencion_contacto
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json={"intencion_contacto": categoria}
            )

        return JSONResponse({
            "tipo": "categoria",
            "agente_activo": agente,
            "intencion_contacto": categoria,
            "mensaje": None
        })

    else:
        # Pregunta aclaratoria — guardar en historial
        historial.append({"role": "user", "content": mensaje})
        historial.append({"role": "assistant", "content": respuesta})
        await guardar_historial(contact_id, historial)

        return JSONResponse({
            "tipo": "pregunta",
            "agente_activo": "none",
            "intencion_contacto": None,
            "mensaje": respuesta
        })


@app.post("/productos")
async def productos(request: Request):
    body = await request.json()
    contact_id = str(body.get("contact_id", ""))
    mensaje = body.get("mensaje_usuario", "")

    if not contact_id or not mensaje:
        return JSONResponse({
            "respuesta": "No pude procesar tu mensaje. Intentá de nuevo.",
            "siguiente_agente": "productos",
            "reclamo_completo": False,
            "nombre_producto_defectuoso": "",
            "n_lote_producto_defectuoso": "",
            "mail_reclamo_cliente": "",
            "descripcion_problema_reclamos": ""
        })

    historial = await get_historial(contact_id)
    if len(historial) > 40:
        historial = historial[-40:]

    historial.append({"role": "user", "content": mensaje})
    respuesta_raw = await llamar_claude(SYSTEM_PROMPT_PRODUCTOS, historial, max_tokens=700)

    if not respuesta_raw:
        return JSONResponse({
            "respuesta": "Hubo un error. Intentá de nuevo.",
            "siguiente_agente": "productos",
            "reclamo_completo": False,
            "nombre_producto_defectuoso": "",
            "n_lote_producto_defectuoso": "",
            "mail_reclamo_cliente": "",
            "descripcion_problema_reclamos": ""
        })

    texto, json_data = parsear_respuesta(respuesta_raw)

    historial.append({"role": "assistant", "content": texto})
    await guardar_historial(contact_id, historial)
    await guardar_log(contact_id, "productos", mensaje, texto)

    siguiente_agente = json_data.get("siguiente_agente", "productos") or "productos"

    # Si cambia de agente, actualizar Supabase
    if siguiente_agente in ["leads", "proveedores"]:
        await set_agente_activo(contact_id, siguiente_agente)

    return JSONResponse({
        "respuesta": texto,
        "siguiente_agente": siguiente_agente,
        "reclamo_completo": json_data.get("reclamo_completo", False),
        "nombre_producto_defectuoso": json_data.get("nombre_producto_defectuoso", ""),
        "n_lote_producto_defectuoso": json_data.get("n_lote_producto_defectuoso", ""),
        "mail_reclamo_cliente": json_data.get("mail_reclamo_cliente", ""),
        "descripcion_problema_reclamos": json_data.get("descripcion_problema_reclamos", "")
    })


@app.post("/leads")
async def leads(request: Request):
    body = await request.json()
    contact_id = str(body.get("contact_id", ""))
    mensaje = body.get("mensaje_usuario", "")

    if not contact_id or not mensaje:
        return JSONResponse({
            "respuesta": "No pude procesar tu mensaje. Intentá de nuevo.",
            "siguiente_agente": "leads",
            "recoleccion_completa": False,
            "nombre_contacto_vendedor": "", "nombre_comercio": "",
            "mail_comercio_vendedor": "", "ciudad_comercio_vendedor": "",
            "direccion_potencial_cliente": "", "tipo_empresa_vendedor": "",
            "volumen_comercio_vendedor": "", "mensaje_adicional_potencial_cliente": ""
        })

    historial = await get_historial(contact_id)
    if len(historial) > 40:
        historial = historial[-40:]

    historial.append({"role": "user", "content": mensaje})
    respuesta_raw = await llamar_claude(SYSTEM_PROMPT_LEADS, historial, max_tokens=700)

    if not respuesta_raw:
        return JSONResponse({
            "respuesta": "Hubo un error. Intentá de nuevo.",
            "siguiente_agente": "leads",
            "recoleccion_completa": False,
            "nombre_contacto_vendedor": "", "nombre_comercio": "",
            "mail_comercio_vendedor": "", "ciudad_comercio_vendedor": "",
            "direccion_potencial_cliente": "", "tipo_empresa_vendedor": "",
            "volumen_comercio_vendedor": "", "mensaje_adicional_potencial_cliente": ""
        })

    texto, json_data = parsear_respuesta(respuesta_raw)

    historial.append({"role": "assistant", "content": texto})
    await guardar_historial(contact_id, historial)
    await guardar_log(contact_id, "leads", mensaje, texto)

    recoleccion_completa = json_data.get("recoleccion_completa", False)
    siguiente_agente = json_data.get("siguiente_agente", "leads") or "leads"

    if siguiente_agente == "none":
        await set_agente_activo(contact_id, "none")
    elif siguiente_agente in ["productos", "proveedores"]:
        await set_agente_activo(contact_id, siguiente_agente)

    return JSONResponse({
        "respuesta": texto,
        "siguiente_agente": siguiente_agente,
        "recoleccion_completa": recoleccion_completa,
        "nombre_contacto_vendedor": json_data.get("nombre_contacto_vendedor", ""),
        "nombre_comercio": json_data.get("nombre_comercio", ""),
        "mail_comercio_vendedor": json_data.get("mail_comercio_vendedor", ""),
        "ciudad_comercio_vendedor": json_data.get("ciudad_comercio_vendedor", ""),
        "direccion_potencial_cliente": json_data.get("direccion_potencial_cliente", ""),
        "tipo_empresa_vendedor": json_data.get("tipo_empresa_vendedor", ""),
        "volumen_comercio_vendedor": json_data.get("volumen_comercio_vendedor", ""),
        "mensaje_adicional_potencial_cliente": json_data.get("mensaje_adicional_potencial_cliente", "")
    })


@app.post("/proveedores")
async def proveedores(request: Request):
    body = await request.json()
    contact_id = str(body.get("contact_id", ""))
    mensaje = body.get("mensaje_usuario", "")

    if not contact_id or not mensaje:
        return JSONResponse({
            "respuesta": "No pude procesar tu mensaje. Intentá de nuevo.",
            "siguiente_agente": "proveedores",
            "recoleccion_completa": False,
            "tipo": "", "nombre_proveedor": "",
            "producto_o_servicio_proveedor": "", "redes_proveedor": "",
            "dato_contacto_proveedor": "", "mail_proveedor": "",
            "cv_archivo_2": "", "comentario_cv": ""
        })

    historial = await get_historial(contact_id)
    if len(historial) > 40:
        historial = historial[-40:]

    historial.append({"role": "user", "content": mensaje})
    respuesta_raw = await llamar_claude(SYSTEM_PROMPT_PROVEEDORES, historial, max_tokens=700)

    if not respuesta_raw:
        return JSONResponse({
            "respuesta": "Hubo un error. Intentá de nuevo.",
            "siguiente_agente": "proveedores",
            "recoleccion_completa": False,
            "tipo": "", "nombre_proveedor": "",
            "producto_o_servicio_proveedor": "", "redes_proveedor": "",
            "dato_contacto_proveedor": "", "mail_proveedor": "",
            "cv_archivo_2": "", "comentario_cv": ""
        })

    texto, json_data = parsear_respuesta(respuesta_raw)

    historial.append({"role": "assistant", "content": texto})
    await guardar_historial(contact_id, historial)
    await guardar_log(contact_id, "proveedores", mensaje, texto)

    recoleccion_completa = json_data.get("recoleccion_completa", False)
    siguiente_agente = json_data.get("siguiente_agente", "proveedores") or "proveedores"

    if siguiente_agente == "none":
        await set_agente_activo(contact_id, "none")
    elif siguiente_agente in ["productos", "leads"]:
        await set_agente_activo(contact_id, siguiente_agente)

    return JSONResponse({
        "respuesta": texto,
        "siguiente_agente": siguiente_agente,
        "recoleccion_completa": recoleccion_completa,
        "tipo": json_data.get("tipo", ""),
        "nombre_proveedor": json_data.get("nombre_proveedor", ""),
        "producto_o_servicio_proveedor": json_data.get("producto_o_servicio_proveedor", ""),
        "redes_proveedor": json_data.get("redes_proveedor", ""),
        "dato_contacto_proveedor": json_data.get("dato_contacto_proveedor", ""),
        "mail_proveedor": json_data.get("mail_proveedor", ""),
        "cv_archivo_2": json_data.get("cv_archivo_2", ""),
        "comentario_cv": json_data.get("comentario_cv", "")
    })
