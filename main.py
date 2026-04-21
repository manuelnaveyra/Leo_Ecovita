from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import os
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

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

SYSTEM_PROMPT = """Sos Leo, el asistente virtual de Ecovita, empresa argentina que fabrica productos de limpieza y cuidado del hogar.

PERSONALIDAD: amigable, directo, con onda. Hablás en español rioplatense. Mensajes cortos de 2-3 líneas máximo. Sin bullets ni listas.

CATÁLOGO ECOVITA 2026:

JABONES LÍQUIDOS PARA ROPA:
- Evolution: doypack 800ml y 3L, botella 800ml y 3L. Fórmula equilibrada para el día a día. Versión baja espuma para lavarropas automático.
- Intense: doypack 800ml y 3L. Más fragancia por más tiempo.
- Clásico Bebé: doypack 3L. Cuida ropa de bebé, libre de colorantes y enzimas.
- Para Diluir: botella 500ml concentrado, rinde 3 litros.
- Sport: doypack 800ml. Cuida prendas deportivas, rinde 8 lavados.
- De Origen Vegetal: doypack 800ml.
- Bebé: doypack 800ml. Fórmula hipoalergénica.

SUAVIZANTES:
- Flores Silvestres: doypack 900ml. Suavidad y fragancia duradera.
- Épico: doypack 900ml. Inspirado en fragancias finas, con óleo de argán.
- Único: doypack 900ml. Inspirado en fragancias finas, con óleo de argán.
- Bouquet: doypack 900ml.
- Lirios y Ylang Ylang: doypack 900ml y 3L.
- Orquídeas y Flores de Muguet: doypack 900ml.
- Suavizante Concentrado Épico y Único: botella 500ml, rinde 22 lavados.
- Apresto Lirios: doypack 500ml. Extiende fragancia, facilita el planchado.

SÚPER CONCENTRADOS PARA DILUIR:
- Sachet 27ml rinde 800ml / 150ml rinde 5L: Limpiador de Pisos Lavanda, Coco y Vainilla, Jabón Líquido, Lavavajillas Limón.
- Sobre + Envase: mismas variedades, incluye botella.

LIMPIADORES DE SUPERFICIES:
- Antigrasa: gatillo 500ml y doypack 500ml.
- Vidrios y Multiuso: gatillo 500ml y doypack 500ml.
- Baños: doypack 500ml.
- Madera: doypack 380ml. Sin residuos, limpia y cuida muebles.
- Multisuperficies Cuero y Metal: gatillo 400ml.

LAVAVAJILLAS:
- Detergente Limón: doypack 450ml. Ultra concentrado, elimina la grasa.
- Neutro: botella 500ml. Desengrasa en una pasada.
- Esponja Clásica y con Salvauñas.

REPELENTES:
- Espirales contra mosquitos: 12 unidades.

CONTACTO: ventas@ecovita.com.ar / +54 9 11 2235-7008 / ecovita.com.ar

OBJETIVO: entender qué necesita el usuario y clasificarlo en: A=quiere vender productos Ecovita en su comercio, B=consumidor con consulta sobre productos, C=quiere ser proveedor, D=quiere saber dónde comprar, E=quiere trabajar en Ecovita.

REGLAS:
- Máximo 2 preguntas antes de clasificar.
- Si el primer mensaje ya es claro, clasificá directo.
- Cuando clasificás, avisale que lo conectás con quien corresponde.
- Si preguntan por un producto específico, respondé con info concreta del catálogo.
- Si preguntan qué producto les conviene, hacé una pregunta y recomendá el más adecuado.
- Nunca inventes productos que no están en el catálogo.
- No des precios, derivá a ventas@ecovita.com.ar o +54 9 11 2235-7008.

RESPUESTA: solo texto plano, sin JSON, sin formato especial."""


async def get_historial(contact_id: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            params={"contact_id": f"eq.{contact_id}", "select": "historial"}
        )
        data = r.json()
        if data:
            return data[0]["historial"]
        return []


async def guardar_historial(contact_id: str, historial: list):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            params={"contact_id": f"eq.{contact_id}", "select": "id"}
        )
        existe = r.json()

        if existe:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json={"historial": historial, "actualizado_en": datetime.utcnow().isoformat()}
            )
        else:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                json={"contact_id": contact_id, "historial": historial, "actualizado_en": datetime.utcnow().isoformat()}
            )


@app.post("/leo")
async def leo(request: Request):
    body = await request.json()
    contact_id = str(body.get("contact_id", ""))
    mensaje = body.get("mensaje", "")

    if not contact_id or not mensaje:
        return JSONResponse({"respuesta": "No pude procesar tu mensaje. Intentá de nuevo."})

    historial = await get_historial(contact_id)

    if len(historial) > 20:
        historial = historial[-20:]

    historial.append({"role": "user", "content": mensaje})

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
                "max_tokens": 500,
                "system": SYSTEM_PROMPT,
                "messages": historial
            }
        )
        data = r.json()
        if "content" not in data:
            return JSONResponse({"respuesta": "Hubo un error procesando tu mensaje. Intentá de nuevo."})
        respuesta = data["content"][0]["text"]

    historial.append({"role": "assistant", "content": respuesta})
    await guardar_historial(contact_id, historial)

    return JSONResponse({"respuesta": respuesta})


@app.get("/")
async def health():
    return {"status": "Leo activo"}

import re

SYSTEM_PROMPT_ORQUESTADOR = """Sos un clasificador de intenciones para Ecovita. Tu única función es analizar el mensaje y asignar UNA categoría. No respondés preguntas ni das información.

CATEGORÍAS:
A - Quiere comprar productos Ecovita para revender en su comercio, ser distribuidor, o comprar en bulto/cajas para negocio propio.
B - Consumidor final: reclamos, preguntas sobre productos, conocer productos o redes de Ecovita, comentarios genéricos.
C - Empresa o persona que quiere OFRECER sus productos o servicios A Ecovita. Son proveedores de Ecovita, no clientes. Ejemplo: empresa química que quiere venderle materias primas a Ecovita.
D - Quiere saber dónde comprar productos Ecovita para consumo personal, o comprar Ecosmart en bulto para diluir.
E - Persona física que quiere trabajar en Ecovita en relación de dependencia, dejar CV. NO es una empresa, es un individuo buscando empleo.

REGLA CLAVE:
- Si una empresa quiere OFRECER productos o servicios A Ecovita → siempre es C.
- Si una empresa quiere COMPRAR o REVENDER productos DE Ecovita → siempre es A.

INSTRUCCIONES:
1. Si la intención es clara → respondé SOLO la letra.
2. Si hay ambigüedad → hacé UNA pregunta corta y cordial para clarificar. En la siguiente respuesta elegí la más probable y respondé SOLO la letra.
3. Cuando tenés la categoría → respondés ÚNICAMENTE la letra. Sin puntos, sin espacios, sin explicaciones.
4. Solo podés hacer UNA pregunta aclaratoria en toda la conversación.
5. Nunca des información sobre Ecovita ni sus productos."""


@app.post("/orquestador")
async def orquestador(request: Request):
    body = await request.json()
    contact_id = str(body.get("contact_id", ""))
    mensaje = body.get("mensaje_usuario", "")

    if not contact_id or not mensaje:
        return JSONResponse({"tipo": "error", "mensaje": "Faltan datos."})

    historial = await get_historial(contact_id)
    if len(historial) > 20:
        historial = historial[-20:]

    mensajes = historial + [{"role": "user", "content": mensaje}]

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
                "max_tokens": 100,
                "system": SYSTEM_PROMPT_ORQUESTADOR,
                "messages": mensajes
            }
        )
        data = r.json()
        if "content" not in data:
            return JSONResponse({"tipo": "error", "mensaje": str(data)})

        respuesta = data["content"][0]["text"].strip()

    es_categoria = bool(re.match(r'^[ABCDE]$', respuesta.upper()))

    if es_categoria:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json"
                },
                params={"contact_id": f"eq.{contact_id}"},
                json={"intencion_contacto": respuesta.upper()}
            )

        return JSONResponse({
            "tipo": "categoria",
            "intencion_contacto": respuesta.upper(),
            "mensaje": None
        })
    else:
        historial.append({"role": "user", "content": mensaje})
        historial.append({"role": "assistant", "content": respuesta})
        await guardar_historial(contact_id, historial)

        return JSONResponse({
            "tipo": "pregunta",
            "intencion_contacto": None,
            "mensaje": respuesta
        })


@app.get("/")
async def health():
    return {"status": "Leo activo"}
