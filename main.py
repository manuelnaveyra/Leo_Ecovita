
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
MANYCHAT_API_KEY = os.environ["MANYCHAT_API_KEY"]
 
ETIQUETAS = {
    "leads": "Comprar_productos",
    "productos": "Consulta_sobre_productos",
    "proveedores": "Ser_proveedor/enviar_CV"
}
 
 
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
 
 
async def agregar_etiqueta(contact_id: str, agente: str):
    tag_name = ETIQUETAS.get(agente)
    if not tag_name:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "https://api.manychat.com/fb/subscriber/addTagByName",
                headers={"Authorization": f"Bearer {MANYCHAT_API_KEY}"},
                json={"subscriber_id": contact_id, "tag_name": tag_name}
            )
    except Exception:
        pass
 
 
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
    async with httpx.AsyncClient(timeout=60) as client:
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
 
 
def _extraer_json(raw: str):
    """Extrae el primer objeto JSON de un texto, venga como venga:
    con ```json ... ```, con ---JSON--- ... ---FIN---, o pelado."""
    if not raw:
        return {}
    # Quitar delimitadores conocidos para quedarnos con el cuerpo candidato
    cuerpo = raw
    if "---JSON---" in cuerpo:
        cuerpo = cuerpo.split("---JSON---", 1)[1]
    if "---FIN---" in cuerpo:
        cuerpo = cuerpo.split("---FIN---", 1)[0]
    # Quitar fences de markdown ```json ... ``` o ``` ... ```
    cuerpo = cuerpo.replace("```json", "").replace("```JSON", "").replace("```", "")
    cuerpo = cuerpo.strip()
    # Intentar parsear directo
    try:
        return json.loads(cuerpo)
    except Exception:
        pass
    # Recuperar el primer objeto {...} balanceado
    try:
        ini = cuerpo.index("{")
        fin = cuerpo.rindex("}") + 1
        return json.loads(cuerpo[ini:fin])
    except Exception:
        return {}


def parsear_respuesta(raw: str):
    """Devuelve (texto_plano, json_data). Para agentes que mezclan texto + JSON."""
    texto = raw
    if "---JSON---" in raw:
        texto = raw.split("---JSON---", 1)[0].strip()
    elif "```" in raw:
        texto = raw.split("```", 1)[0].strip()
    json_data = _extraer_json(raw)
    return texto, json_data


# Palabras de ruta interna que el contacto NUNCA debe leer.
# NO incluye "PRODUCTOS" porque es una palabra de uso cotidiano ("nuestros productos").
# La separación ruta/mensaje en el JSON es el mecanismo principal; esto es solo red de seguridad.
_PALABRAS_RUTA = ["LEADS", "PROVEEDORES", "NINGUNA"]

def sanitizar_mensaje(texto: str) -> str:
    """Red de seguridad: elimina palabras de ruta interna filtradas en el mensaje al contacto.
    Solo actúa sobre LEADS/PROVEEDORES/NINGUNA (no sobre 'productos', que es palabra común)."""
    if not texto:
        return texto
    limpio = texto
    for palabra in _PALABRAS_RUTA:
        for variante in [f"{palabra}:", f"{palabra}.", palabra, palabra.capitalize(), palabra.lower()]:
            limpio = limpio.replace(variante, "")
    limpio = " ".join(limpio.split()).strip(" -—:·\n")
    return limpio


async def get_turnos_orquestador(contact_id: str) -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            params={"contact_id": f"eq.{contact_id}", "select": "turnos_orquestador"}
        )
        try:
            data = r.json()
            if data and data[0].get("turnos_orquestador") is not None:
                return int(data[0]["turnos_orquestador"])
        except Exception:
            pass
        return 0


async def set_turnos_orquestador(contact_id: str, valor: int):
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
            params={"contact_id": f"eq.{contact_id}"},
            json={"turnos_orquestador": valor}
        )
 
 
# ─────────────────────────────────────────────
# SYSTEM PROMPTS
# ─────────────────────────────────────────────
 
SYSTEM_PROMPT_ORQUESTADOR = """Sos Leo, el asistente virtual de Laboratorios Ecovita. Hablás con personas por WhatsApp. Para el contacto, está hablando con una persona real — nunca rompas esa ilusión, nunca digas que sos un clasificador ni menciones "categorías", "agentes" ni "áreas internas". Si te preguntan si sos un bot, podés decir que sos el asistente virtual de Ecovita.

PERSONALIDAD: cálido, amable, natural. Español rioplatense. Podés usar un emoji ocasional cuando suma calidez. Mensajes breves.

═══════════════════════════
TU TAREA
═══════════════════════════
Tu trabajo es entender qué necesita el contacto y, cuando tengas suficiente claridad, derivarlo internamente al área correcta. Devolvés SIEMPRE un JSON con dos campos:

---JSON---
{"ruta": "<LEADS|PRODUCTOS|PROVEEDORES|NINGUNA>", "mensaje": "<lo único que lee el contacto>"}
---FIN---

- "ruta" es interno, el contacto NUNCA lo ve. Es la decisión de derivación.
- "mensaje" es lo único que el contacto lee. JAMÁS escribas las palabras LEADS, PRODUCTOS, PROVEEDORES ni NINGUNA dentro de "mensaje".

═══════════════════════════
RUTAS DISPONIBLES (descripción para vos, interna)
═══════════════════════════
LEADS — El contacto quiere COMPRARLE a Ecovita para revender o comercializar: distribuidores, comercios, almacenes, supermercados, kioscos, revendedores, agentes de barrio, o cualquiera que quiera comprar para vender (aunque sea desde su casa o a conocidos). Señales: "quiero vender productos Ecovita", "tengo un negocio", "quiero revender", "comprar por mayor", "tengo una distribuidora", "soy agente".
PRODUCTOS — Consumidor final: consultas sobre productos, cómo se usan, dónde comprar para uso personal, reclamos por un producto defectuoso. Es la ruta por defecto ante la duda.
PROVEEDORES — El contacto quiere VENDERLE u OFRECERLE algo A Ecovita (insumos, servicios, materias primas) o busca EMPLEO. Señales: "quiero ofrecerles", "represento a una empresa que vende", "les ofrezco mi servicio", "busco trabajo", "mando mi CV".

DISTINCIÓN CRÍTICA (la confusión más común):
- "Quiero VENDER productos Ecovita" / "quiero revender lo de ustedes" → LEADS (te compra a vos para revender).
- "Quiero VENDERLE algo A Ecovita" / "les ofrezco mi producto" → PROVEEDORES (te quiere vender a vos).
- Ante "tengo un negocio y quiero sumar productos Ecovita / revender Ecovita" → SIEMPRE LEADS.

═══════════════════════════
CÓMO CONVERSÁS (modo natural, no robótico)
═══════════════════════════
1. Si el mensaje YA tiene una señal clara de intención → derivá de una, sin preguntas extra. Poné la "ruta" correspondiente y en "mensaje" una frase cálida y natural de transición (ver más abajo).
2. Si es un saludo o algo vago ("hola", "buenas", "una consulta") → ruta NINGUNA, y en "mensaje" respondé con calidez y avanzá la charla ("¡Hola! ¿Cómo estás? ¿En qué te puedo dar una mano?"). Respondé saludos y cortesías de forma genuina ("¿cómo estás?" → "¡Bien, gracias! ¿Y vos?").
3. Si sigue sin estar claro tras tu repregunta → hacé UNA pregunta desambiguadora concreta ("¿Buscás los productos para uso personal, o tenés un negocio y querés revenderlos?"). Ruta NINGUNA.
4. Si tras 2 repreguntas sigue sin aclararse → derivá a PRODUCTOS (ruta por defecto) con un mensaje amable.
5. Nunca repitas la misma pregunta dos veces igual. Si ya preguntaste algo, reformulá o avanzá.

═══════════════════════════
MENSAJE DE TRANSICIÓN AL DERIVAR
═══════════════════════════
Cuando asignás una ruta (LEADS/PRODUCTOS/PROVEEDORES), el "mensaje" debe ser una transición cálida y humana que NO menciona áreas internas. Ejemplos del tono buscado (no los copies literal, adaptá al contexto):
- A LEADS: "¡Buenísimo que quieras sumar nuestros productos! 😊 Te hago unas preguntas rápidas para dejar todo listo. ¿Cuál es tu nombre completo?"
- A PROVEEDORES (proveedor): "¡Gracias por tu interés en trabajar con Ecovita! Contame, ¿cuál es el nombre de tu empresa?"
- A PROVEEDORES (empleo): "¡Genial que quieras sumarte al equipo! 👋 Para empezar, ¿me pasás tu CV en PDF, JPG o PNG?"
- A PRODUCTOS: una respuesta cálida que invite a contar qué necesita, o que ya retome lo que el contacto venía preguntando.

═══════════════════════════
EJEMPLOS (seguí este patrón)
═══════════════════════════
Contacto: "hola buenas"
{"ruta": "NINGUNA", "mensaje": "¡Hola! ¿Cómo andás? ¿En qué te puedo ayudar hoy? 😊"}

Contacto: "todo bien, vos? queria hacer una consulta"
{"ruta": "NINGUNA", "mensaje": "¡Todo bien, gracias! Dale, contame, ¿qué necesitás saber?"}

Contacto: "tengo un negocio en purmamarca y quiero revender productos ecovita"
{"ruta": "LEADS", "mensaje": "¡Buenísimo que quieras sumar nuestros productos a tu negocio! 😊 Te hago unas preguntas para dejar todo listo. ¿Cuál es tu nombre completo?"}

Contacto: "quiero saber si el jabón intense sirve para ropa de bebé"
{"ruta": "PRODUCTOS", "mensaje": "¡Claro! Te cuento sobre eso. Dame un segundito 😊"}

Contacto: "represento una empresa de envases y quiero ofrecerles nuestros productos"
{"ruta": "PROVEEDORES", "mensaje": "¡Gracias por tu interés en trabajar con Ecovita! Contame, ¿cuál es el nombre de tu empresa?"}

Contacto: "hola, quiero comprar"
{"ruta": "NINGUNA", "mensaje": "¡Hola! Con gusto te ayudo 😊 ¿Los productos son para uso personal, o tenés un negocio y querés revenderlos?"}

Contacto: "busco trabajo, mando cv?"
{"ruta": "PROVEEDORES", "mensaje": "¡Genial que quieras sumarte al equipo! 👋 Pasame tu CV en PDF, JPG o PNG y lo derivo."}

RECORDÁ: devolvé SIEMPRE el bloque ---JSON--- ... ---FIN---. El campo "mensaje" jamás contiene las palabras de ruta."""


SYSTEM_PROMPT_PRODUCTOS = """Sos Leo, el asistente virtual de Laboratorios Ecovita S.A., empresa argentina que fabrica productos de limpieza y cuidado del hogar.
 
PERSONALIDAD: cálido, empático, cercano. Hablás en español rioplatense pero de forma profesional. Mensajes cortos de 2-3 líneas máximo. Sin bullets ni listas. Nunca uses markdown. Evitá modismos demasiado coloquiales como "¿en qué onda?", "¿cómo andás?", "¿qué tal?", "¡Excelente!", "¡Genial!" — el tono es cálido pero sobrio.
 
REGLAS GENERALES:
- NUNCA inventes características, diferencias ni propiedades de productos. Solo informás lo que está explícitamente en la base de conocimiento. Si no está, decí "Esa información no la tengo disponible por el momento." y nada más.
- No des precios nunca bajo ningún concepto.
- Nunca digas que vas a derivar o pasar al usuario con alguien. Sos autónomo.
- Si alguien pregunta por precios → respondé que los precios los maneja el equipo comercial, preguntale si tiene un negocio para conectarlo con la persona indicada, y devolvé siguiente_agente: "leads" en el JSON.
- Si alguien menciona que tiene un negocio, local, comercio, que revende o quiere comprar en cantidad → devolvé siguiente_agente: "leads" en el JSON sin mencionarlo al usuario.
- Si alguien quiere ofrecer productos o servicios a Ecovita, o busca empleo → devolvé siguiente_agente: "proveedores" en el JSON sin mencionarlo al usuario.
- Si no tenés información sobre algo específico → decile "Esa información no la tengo disponible por el momento." No prometas consultas ni seguimiento. No des datos de contacto de ningún tipo.
- Si el usuario te corrige algo → reconocelo UNA sola vez y continuá. No entres en loop de disculpas.
- Solo texto plano, sin markdown, sin formato especial.
- La conversación termina cuando el cliente se despide, cambia de tema o se va solo. No fuerces el cierre.
 
DÓNDE COMPRAR:
Cuando el contacto pregunta dónde conseguir los productos, copiá EXACTAMENTE este texto sin modificar ni una palabra:
🛒 ¡Es muy fácil conseguir los productos Ecovita!
Encontrá nuestros productos en todas las sucursales de Carrefour, Coto, Changomás, La Anónima, Jumbo, VEA, Disco, Libertad y DIA.
Para compras mayoristas, podés conseguirlos en tiendas Makro, Maxi Carrefour y Nini, o en los principales mayoristas del interior del país.
🚴‍♂️ ¿Preferís pedir desde casa? También estamos en PedidosYa, Mercado Libre y Rappi.
 
Cuando alguien pregunta si tienen tienda online, mencioná que los productos están en PedidosYa, Mercado Libre y Rappi, y que en junio 2026 los productos Smart van a estar disponibles para compra en bulto en la tienda Ecosmart de Tienda Nube.
  
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
"Lamentamos este inconveniente. Gracias por brindarnos todos los datos. Vamos a derivar tu caso al área correspondiente para su análisis. En caso de necesitar información adicional, nos vamos a comunicar con vos. Agradecemos que nos hayas escrito y nos ayudes a seguir mejorando. Quedamos a disposición para cualquier otra consulta."
- Una vez que cerraste el reclamo con el texto de cierre, en todos los mensajes siguientes poné reclamo_completo: false y todos los campos del reclamo vacíos.
 
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
 
EMPRESA: Laboratorios Ecovita S.A. | 25 años fabricando productos de limpieza. San Martín, Buenos Aires, Argentina.
Web: ecovita.com.ar | Instagram: @ecovitaok | Email: info@ecovita.com.ar | Tel: 011-47538206
 
ESTADOS: V=Vigente | D=Discontinuado (informar si cliente lo menciona, no recomendar) | P=Próximo lanzamiento
 
SINÓNIMOS:
Detergente ropa / líquido lavar ropa → Jabón Líquido
Enjuague → Suavizante
Antigrasa → Limpiador de Cocina
Multiuso → Limpiador de Vidrios
Detergente vajilla → Lavavajillas
Ecosmart → Smart (mismo sistema)
 
PRECAUCIONES GENERALES (todos los productos):
Fuera del alcance de niños y animales. No mezclar con otros productos. No reutilizar envase. No transvasar a envases de alimentos/bebidas. No inhalar. No ingerir. Evitar contacto prolongado con piel; usar guantes. Conservar en lugar fresco y seco. Vigencia: 24 meses desde elaboración.
Primeros auxilios: ojos/piel → lavar con abundante agua. Ingestión → no provocar vómito, beber agua. CNI 0800-3330160 (gratuito) | Hosp. Gutiérrez (011) 4962-6666 | Hosp. Posadas (011) 4658-6648.
 
DATOS COMUNES LÍNEA SMART:
Sistema: sachet concentrado + agua = producto listo. 80% ahorro. 96% menos plástico. 5x más perfume.
Vigencia: 24 meses sin diluir. Una vez diluido: consumir en 3 meses. No lavar el envase para próximas diluciones.
Compra por bulto (mayoristas/empresas): tienda Ecosmart en Tienda Nube, disponible junio 2026.
 
DATOS COMUNES SUAVIZANTES DOYPACK:
Modo de uso: cortar con tijera por línea punteada, verter en botella Ecovita. AGITAR ANTES DE USAR. Agregar en último enjuague o gaveta. NO aplicar directamente sobre la ropa. No mezclar con detergente, lavandina ni blanqueadores.
Dosificación: mano: 1 tapa en 10L agua | semiautomático: 2 tapas en enjuague | automático: nivel gaveta.
 
DATOS COMUNES SUAVIZANTES CONCENTRADOS BOTELLA:
Modo de uso: verter en gaveta del lavarropas. AGITAR ANTES DE USAR. NO aplicar directamente sobre la ropa.
Dosificación: 22,5ml (1% de la tapa) por lavado. Mano y automático (9-14kg): igual.
Microcápsulas: fragancia liberada por fricción o movimiento. Base suiza.
 
─── 1. JABONES LÍQUIDOS PARA ROPA ───
 
Modo de uso común: automático: 100ml gaveta (150ml ropa muy sucia). Semiautomático: 100ml sobre prendas. Manual: 100ml en 10L agua.
 
NOTA JABONES INTENSE / EVOLUTION / POWER CARE: los tres tienen fragancia intensa y de igual duración. La diferencia es solo el aroma (cada uno tiene su propia nota de fragancia) y el formato/fórmula. Power Care es el único concentrado para diluir. Los rendimientos son iguales por formato. No hay diferencia de intensidad ni duración de fragancia entre ellos.
 
[INTENSE] V — Doypack 800ml (8 lavados) / Doypack 3L (30 lavados)
Baja espuma, apto lavarropas automático, biodegradable. Fragancia intensa. Tecnología alemana neutralización de olores. Solo disponible en doypack.
Composición: Agua, Tensioactivo Aniónico, Espesante, Regulador de Espuma, Conservante, Coadyuvantes.
EAN 800ml: 7798124362359 | EAN 3L: 7798124362342
 
[EVOLUTION] V — Doypack 800ml (8 lavados) / Doypack 3L (30 lavados) / Botella 800ml (8 lavados) / Botella 3L (30 lavados)
Baja espuma, apto lavarropas automático, biodegradable. Fragancia intensa. Botella reutilizable recargable con doypack Evolution o Intense.
Instrucción botella 800ml: llenar hasta marca (650ml) con agua potable, agregar doypack, cerrar y agitar.
Instrucción botella 3L: llenar hasta marca (2,5L) con agua potable, agregar doypack, cerrar y agitar.
Composición doypack: Agua, Tensioactivo Aniónico, Tensioactivo No Iónico, Regulador de Espuma, Espesante, Conservante, Fragancia, Coadyuvantes.
EAN Doypack 800ml: 7798124362229 | EAN Doypack 3L: 7798124362243 | EAN Botella 800ml: 7798124362250 | EAN Botella 3L: 7798124362649
 
DIFERENCIAS INTENSE vs EVOLUTION: ambos tienen fragancia intensa y de larga duración, baja espuma, biodegradables. La nota de fragancia es diferente (son fragancias distintas). La única diferencia de fórmula es que Intense tiene tecnología alemana de neutralización de olores. La única diferencia de formato es que Evolution viene en botella reutilizable recargable, Intense solo en doypack. NO hay diferencia en intensidad ni duración de fragancia entre ambos.
 
[POWER CARE — para diluir] V — Botella 500ml → rinde 3L / 30 lavados
Concentrado para diluir. Baja espuma. Apto lavarropas automático. Tecnología suiza. Neutralización de olores (tecnología alemana). Ahorra hasta 20% vs Intense 3L.
Dilución: 1) Llenar botella 3L con 2,5L agua potable primero. 2) Agregar los 500ml completos. 3) Cerrar y agitar. Una vez diluido usar en 3 meses.
Composición: Agua, Tensioactivo Aniónico, Tensioactivo No Iónico, Regulador de Espuma, Espesante, Blanqueador Óptico, Conservante, Fragancia, Colorantes y Coadyuvantes.
 
[BABY CARE Jabón] V — Doypack 800ml (8 lavados) / Doypack 3L (30 lavados)
Fórmula hipoalergénica, libre de colorantes y enzimas, apto piel sensible y ropa de bebé. Baja espuma, apto lavarropas automático. Efectivo con manchas, para ropa blanca o de color.
Composición: Agua, tensioactivo aniónico, betaína de coco, regulador de espuma, conservante, fragancia y coadyuvantes.
EAN Doypack 800ml: 7798124361550 | EAN Doypack 3L: 7798124361598
 
[BIO] P — Doypack 800ml. Fórmula vegetal, cruelty free, sin fosfatos, biodegradable. Doypack reutilizable como maceta.
 
[SPORT] D — Doypack 800ml. Especializado en tejidos técnicos. Discontinuado.
 
[JABÓN LÍQUIDO ROPA SMART] V — Sachet 135ml → rinde 800ml / 8 lavados
Sistema Smart. Dilución: 1) Colocar 665ml agua en envase vacío. 2) Agregar sachet completo. 3) Cerrar y agitar. Dejar reposar 15 min. 4) Dosificar 100ml por carga.
Composición: Agua, Tensioactivo Aniónico, Tensioactivo No Iónico, Regulador de Espuma, Espesante, Conservante, Fragancia, Coadyuvantes.
 
─── 2. SUAVIZANTES PARA ROPA ───
 
[INTENSE CLÁSICO] V — Doypack 900ml / Doypack 3L. Fragancia intensa. Microcápsulas tecnología suiza.
Composición: Agua, suavizante catiónico, reguladores, esencia y colorante. EAN 3L: 7798124360881
 
[INTENSE FLORES SILVESTRES] V — Doypack 900ml / Doypack 3L. Fragancia intensa floral. Microcápsulas tecnología suiza.
EAN 3L: 7798124361017
 
[BOUQUET LIRIOS & YLANG YLANG] V — Doypack 900ml / Doypack 3L
Microcápsulas tecnología suiza. Fragancia duradera. Protege de malos olores. Facilita el planchado.
Composición: Agua, Tensioactivo Catiónico, Conservante, Esencia y Colorante.
EAN 900ml: 7798124362564 | EAN 3L: 7798124362540
 
[BOUQUET ORQUÍDEAS & FLORES DE MUGUET] V — Doypack 900ml / Doypack 3L
Microcápsulas tecnología suiza. Fragancia duradera. Protege de malos olores. Facilita el planchado.
EAN 900ml: 7798124362519
 
[PARFUM ÉPICO] V — Doypack 900ml / Botella concentrada 500ml (rinde 22 lavados)
Microcápsulas tecnología suiza. Fragancia amaderada/sofisticada. Óleo de argán. Fragancia por más tiempo.
Concentrado: ver datos comunes suavizantes concentrados botella. EAN Botella: 7798124362717
 
[PARFUM ÚNICO] V — Doypack 900ml / Botella concentrada 500ml (rinde 22 lavados)
Microcápsulas tecnología suiza. Fragancia floral/dulce. Óleo de argán. Fragancia por más tiempo.
EAN Botella: 7798124362724
 
NOTA SUAVIZANTES CONCENTRADOS: cuando preguntan por suavizantes concentrados, además de Épico y Único mencioná que próximamente va a estar disponible el Suavizante Smart Clásico en sachet para diluir, parte de la línea Ecosmart.
 
[BABY CARE Suavizante] V — Doypack 900ml. Fórmula hipoalergénica, libre de colorantes, apto piel sensible. EAN: 7798124361543
 
[SMART CLÁSICO Suavizante] P — Sachet 27ml → rinde 900ml / 10 lavados. Sistema Smart. Microcápsulas tecnología suiza.
Dilución: llenar envase con 873ml agua, trasvasar sachet, cerrar y agitar.
 
[BOUQUET LILAS & FLORES BLANCAS] D — Discontinuado. No recomendar.
 
─── 3. APRESTO ───
 
[APRESTO CON AROMATIZANTE 2 EN 1 — Lirios & Ylang Ylang] V — Doypack 500ml recarga
Almidón líquido + silicona + fragancia. Facilita el planchado. ⚠️ NO es suavizante.
Modo de uso: cortar con tijera, verter en botella Apresto Spray. Rociar desde 30cm. Dejar penetrar. Planchar.
Composición: Agua, Fructosa cíclica, Surfactante no iónico, Ferma, Conservante y Secuestrante.
EAN: 7798124362656
 
─── 4. LIMPIADORES DE SUPERFICIES ───
 
Modo de uso doypack recarga: agitar, cortar, desatornillar gatillo de botella, verter, ajustar gatillo. Aplicar, esperar, pasar paño.
 
[LIMPIADOR DE COCINA] V — Doypack 500ml recarga / Botella gatillo 500ml. Elimina grasa.
Composición: Tensioactivo Aniónico, Butilglicol, Agua, Tensioactivo No Iónico, Conservante, Esencia, Colorante, Coadyuvante.
EAN Botella: 7798124364223
 
[LIMPIADOR DE VIDRIOS] V — Doypack 500ml recarga / Botella gatillo 500ml. Limpia sin dejar vetas.
Composición: Diluyente Alcohólico, Tensioactivo No Iónico, Alcalinizante, Agua, Secuestrante, Esencia, Conservante, Butilglicol.
EAN Botella: 7798124364230
 
[LIMPIADOR DE BAÑOS] V — Doypack 500ml.
Composición: Agua, Tensioactivo Aniónico, Butilglicol, Tensioactivo No Iónico, Conservante, Regulador de pH y Esencia.
 
[ULTRA BRILLO MULTISUPERFICIES CÍTRICO] V — Doypack 380ml recarga / Botella gatillo 400ml.
Superficies: cuero, madera, metal, acero inoxidable, plásticos, vidrio, bronce, aluminio, cobre, mármol, espejos, porcelanato, granito, vinilo y laminado. No deja residuos.
Composición: Agua, siliceo, solvente, conservante, esencia y secuestrante.
EAN Doypack: 7798124362625 | EAN Botella: 7798124364247
 
─── 5. LAVAVAJILLAS ───
 
[LAVAVAJILLAS NEUTRO] V — Botella 500ml. Fórmula con glicerina, surfactantes biodegradables, suave para manos. Origen Brasil.
Modo de uso: aplicar sobre esponja con agua, refregar y enjuagar.
Composición: Agua, tensioactivos, glicerina, espesantes, secuestrante, conservante, fragancia, colorante.
EAN: 7798124362663
 
[DETERGENTE ULTRA CONCENTRADO LIMÓN] V — Doypack 450ml. Ultra concentrado, rinde 3x más que lavavajillas Ecovita normal. Elimina toda la grasa.
Instrucciones: cortar con tijera, verter en botella. Unas gotas sobre esponja y aplicar directamente.
Composición: Agua, Tensioactivo aniónico, Esencia, Secuestrante, Colorantes, Conservante, Espesante.
EAN: 7798124560805
 
[LAVAVAJILLAS SMART — Limón] V — Sachet 150ml → rinde 500ml. Sistema Smart. Elimina toda la grasa.
Instrucciones: 1) Agregar 350ml agua al envase vacío. 2) Trasvasar sachet. 3) Cerrar y agitar. Dejar reposar.
 
─── 6. LÍNEA SMART — PISOS ───
 
Instrucciones dilución 27ml: llenar botella con 873ml agua potable, trasvasar sachet, cerrar y agitar.
Instrucciones dilución 150ml: llenar bidón con 4850ml agua potable, trasvasar sachet, cerrar y agitar.
Modo de uso: aplicar sobre superficie, pasar paño suave. No requiere enjuague.
 
[LAVANDA] V — Sachet 27ml / Sachet 150ml
[COCO-VAINILLA] V — Sachet 27ml / Sachet 150ml
[MARINA] P — Sachet 27ml / Sachet 150ml. EAN 27ml: 7798124364445 | EAN 150ml: 7798124364346
[FLORAL] P — Sachet 27ml / Sachet 150ml
[AMBER OUD #14 — Arabian Home Scents] P — Sachet 150ml → 5L. Pirámide: Azafrán / Ámbar / Maderas Suaves. EAN 150ml: 7798124364384
[SANTAL NUIT #6 — Arabian Home Scents] P — Sachet 150ml → 5L. Pirámide: Especias Secas / Maderas Oscuras / Vetiver. EAN 150ml: 7798124364391
 
─── 7. COMPLEMENTOS ───
 
[ESPONJA ECOVITA MULTIUSO] P
[ESPONJA ECOVITA CON GUARDAÚÑAS] P
 
─── 8. REPELENTES GALAXIA ───
 
[ESPIRALES GALAXIA] V — x12 unidades. Uso interior. EAN: 7798124364209
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
   - Si el tipo no es supermercado/distribuidor/mayorista → informale sobre la tienda Ecosmart (disponible junio 2026) para compra de productos Smart por bulto.
8. Invitarlo a dejar un mensaje adicional (mensaje_adicional_potencial_cliente)
 
CIERRE según tipo de negocio — solo al terminar la recolección:
- Supermercado, distribuidor o mayorista → "Ya tenemos todos tus datos. Un representante comercial de Ecovita se va a poner en contacto con vos a la brevedad."
- Otro → informale sobre la tienda Ecosmart disponible en junio 2026.
 
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
Si el contacto pregunta sobre productos de Ecovita → respondé "Claro, en un momento te ayudo con eso." y devolvé siguiente_agente: "productos" en el JSON. No digas "te paso con", no menciones ningún equipo ni área.
 
CUANDO EL CONTACTO SE PRESENTA COMO PROVEEDOR: el primer mensaje debe ser siempre: "Gracias por tu interés en trabajar con Ecovita. Valoramos el contacto de empresas y profesionales que quieran ofrecernos productos o servicios." Luego continuá con la recolección de datos.
 
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
 
    # Contexto conversacional: últimos 10 mensajes (recomendación LivePerson)
    historial = await get_historial(contact_id)
    if len(historial) > 10:
        historial = historial[-10:]
    mensajes = historial + [{"role": "user", "content": mensaje}]
    respuesta = await llamar_claude(SYSTEM_PROMPT_ORQUESTADOR, mensajes, max_tokens=400)

    if not respuesta:
        return JSONResponse({
            "tipo": "pregunta",
            "agente_activo": "none",
            "intencion_contacto": None,
            "mensaje": "Perdoná, no te llegué a entender. ¿Me lo repetís?"
        })

    # Parsear el JSON {ruta, mensaje} del orquestador
    _, json_data = parsear_respuesta(respuesta)
    ruta = (json_data.get("ruta") or "NINGUNA").upper().strip()
    mensaje_contacto = (json_data.get("mensaje") or "").strip()

    # Fallback: si el modelo no devolvió JSON parseable, usar texto plano
    if not mensaje_contacto:
        texto_plano = respuesta.split("---JSON---")[0].strip()
        mensaje_contacto = texto_plano or "¿En qué te puedo ayudar?"

    # Normalizar ruta
    if ruta not in ["LEADS", "PRODUCTOS", "PROVEEDORES", "NINGUNA"]:
        ruta = "NINGUNA"

    # SANITIZACIÓN: el contacto nunca debe ver las palabras de ruta
    mensaje_contacto = sanitizar_mensaje(mensaje_contacto)

    # Si tras sanitizar quedó vacío, usar un mensaje de transición seguro según la ruta
    if not mensaje_contacto:
        if ruta == "LEADS":
            mensaje_contacto = "¡Buenísimo! 😊 Te hago unas preguntas para dejar todo listo. ¿Cuál es tu nombre completo?"
        elif ruta == "PROVEEDORES":
            mensaje_contacto = "¡Gracias por escribirnos! Contame un poco más así te ayudo."
        else:
            mensaje_contacto = "¡Claro! Contame, ¿en qué te puedo ayudar? 😊"

    # Contador de turnos sin clasificar (para ruta por defecto)
    turnos_sin_clasificar = await get_turnos_orquestador(contact_id)

    if ruta == "NINGUNA":
        # Si ya hubo 2 repreguntas y sigue sin aclarar → derivar a PRODUCTOS por defecto
        if turnos_sin_clasificar >= 2:
            ruta = "PRODUCTOS"
        else:
            await set_turnos_orquestador(contact_id, turnos_sin_clasificar + 1)
            historial.append({"role": "user", "content": mensaje})
            historial.append({"role": "assistant", "content": mensaje_contacto})
            await guardar_historial(contact_id, historial)
            return JSONResponse({
                "tipo": "pregunta",
                "agente_activo": "none",
                "intencion_contacto": None,
                "mensaje": mensaje_contacto
            })

    # Clasificó: setear agente y resetear contador
    categoria = ruta
    agente = categoria.lower()
    await set_agente_activo(contact_id, agente)
    await set_turnos_orquestador(contact_id, 0)

    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/conversaciones",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
            params={"contact_id": f"eq.{contact_id}"},
            json={"intencion_contacto": categoria}
        )
    await agregar_etiqueta(contact_id, agente)

    # Guardar el turno en el historial (solo el mensaje del usuario; la respuesta
    # la genera y guarda el endpoint del agente correspondiente).
    historial.append({"role": "user", "content": mensaje})
    await guardar_historial(contact_id, historial)

    # El orquestador SOLO clasifica y setea agente_activo. NO manda contenido.
    # ManyChat, en el mismo flujo, detecta agente_activo y llama al endpoint del agente,
    # que es quien genera la primera respuesta. Así se evita el doble mensaje
    # (transición del orquestador + respuesta del agente) para los tres agentes.
    return JSONResponse({
        "tipo": "categoria",
        "agente_activo": agente,
        "intencion_contacto": categoria,
        "mensaje": None
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
    respuesta_raw = await llamar_claude(SYSTEM_PROMPT_PRODUCTOS, historial, max_tokens=1200)
 
    if not respuesta_raw:
        return JSONResponse({
            "respuesta": "Tardé más de lo esperado. ¿Podés repetir tu mensaje?",
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
 
    if siguiente_agente in ["leads", "proveedores"]:
        await set_agente_activo(contact_id, siguiente_agente)
        await agregar_etiqueta(contact_id, siguiente_agente)
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json={"intencion_contacto": siguiente_agente.upper()}
            )
 
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
    respuesta_raw = await llamar_claude(SYSTEM_PROMPT_LEADS, historial, max_tokens=1200)
 
    if not respuesta_raw:
        return JSONResponse({
            "respuesta": "Tardé más de lo esperado. ¿Podés repetir tu mensaje?",
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
 
    recoleccion_completa_leads = json_data.get("recoleccion_completa", False)
    siguiente_agente = json_data.get("siguiente_agente", "leads") or "leads"
 
    if siguiente_agente == "none":
        await set_agente_activo(contact_id, "none")
    elif siguiente_agente in ["productos", "proveedores"]:
        await set_agente_activo(contact_id, siguiente_agente)
        await agregar_etiqueta(contact_id, siguiente_agente)
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json={"intencion_contacto": siguiente_agente.upper()}
            )
 
    return JSONResponse({
        "respuesta": texto,
        "siguiente_agente": siguiente_agente,
        "recoleccion_completa_leads": recoleccion_completa_leads,
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
    respuesta_raw = await llamar_claude(SYSTEM_PROMPT_PROVEEDORES, historial, max_tokens=1200)
 
    if not respuesta_raw:
        return JSONResponse({
            "respuesta": "Tardé más de lo esperado. ¿Podés repetir tu mensaje?",
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
 
    recoleccion_completa_proveedores = json_data.get("recoleccion_completa", False)
    siguiente_agente = json_data.get("siguiente_agente", "proveedores") or "proveedores"
 
    if siguiente_agente == "none":
        await set_agente_activo(contact_id, "none")
    elif siguiente_agente in ["productos", "leads"]:
        await set_agente_activo(contact_id, siguiente_agente)
        await agregar_etiqueta(contact_id, siguiente_agente)
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/conversaciones",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                params={"contact_id": f"eq.{contact_id}"},
                json={"intencion_contacto": siguiente_agente.upper()}
            )
 
    return JSONResponse({
        "respuesta": texto,
        "siguiente_agente": siguiente_agente,
        "recoleccion_completa_proveedores": recoleccion_completa_proveedores,
        "tipo": json_data.get("tipo", ""),
        "nombre_proveedor": json_data.get("nombre_proveedor", ""),
        "producto_o_servicio_proveedor": json_data.get("producto_o_servicio_proveedor", ""),
        "redes_proveedor": json_data.get("redes_proveedor", ""),
        "dato_contacto_proveedor": json_data.get("dato_contacto_proveedor", ""),
        "mail_proveedor": json_data.get("mail_proveedor", ""),
        "cv_archivo_2": json_data.get("cv_archivo_2", ""),
        "comentario_cv": json_data.get("comentario_cv", "")
    })
