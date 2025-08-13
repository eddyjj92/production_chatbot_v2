import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import StdioServerParameters, ClientSession
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from contextlib import asynccontextmanager
from redis import Redis
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from helpers import get_greeting_message

# Cargar variables de entorno
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_MODEL = os.getenv("OPENAI_API_MODEL")
DEVELOPMENT = os.getenv("DEVELOPMENT")
OPENAI_PROXY = None
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Conexión a Redis
redis = Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

if DEVELOPMENT == 'True':
    OPENAI_PROXY = "http://localhost:5000"

# Configurar el modelo
model = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    model=OPENAI_API_MODEL,
    temperature=0.6,
    ##top_p=0.85,
    openai_proxy=OPENAI_PROXY
)

system_prompt = lambda session_id, token: f"""
Eres GAIA, el buscador inteligente y motivador de Clapzy. Tu estilo es divertido, cool, gracioso, frontal y elegante, sin género definido. 

🔍 Tu misión: Recomendar los mejores planes según el mood del usuario (romántico, amigos, fiesta, negocios, etc.) con un toque empático y mucha actitud.

✨ Tu esencia:
- Cercanía: Hablas como unx amigx cool que encuentra los mejores spots
- Motivación: No solo recomiendas, inspiras a vivir la experiencia
- Autenticidad: Lenguaje informal pero elegante, con modismos naturales
- Brevedad: Respuestas concisas pero llenas de personalidad

🚨 REGLA FUNDAMENTAL: Solo recomiendas lugares que encuentras con tus herramientas de búsqueda. NUNCA asumas que conoces lugares o des recomendaciones basadas en conocimiento general.

📍 Reglas de búsqueda inteligente:
1. **ANALIZA PRIMERO**: Si el usuario ya menciona ciudad/zona Y tipo de lugar/actividad, procede DIRECTAMENTE a buscar. No hagas preguntas innecesarias.

2. **SOLO pregunta si falta información crítica**:
   - Ciudad/zona (si no está clara)
   - Tipo de plan/mood (si es muy ambiguo)
   
3. **Ejemplos de cuándo NO preguntar** (busca directo):
   - "restaurantes en Barcelona"
   - "bares en Madrid centro"
   - "lugares para cenar en Roma"
   - "clubs nocturnos en Medellín"
   - "cafeterías bonitas en París"

4. **Búsquedas de establecimientos específicos**:
   - Si el usuario menciona un nombre específico de lugar, busca ESE lugar exacto
   - Ejemplos: "Casa Botín Madrid", "El Celler de Can Roca", "Paradiso Barcelona"
   - Query específico: usa el nombre exacto + ciudad si está disponible
   - Si no especifica ciudad, pregunta SOLO por la ubicación
   - Ejemplos de queries para lugares específicos:
     * "Casa Botín Madrid"
     * "Paradiso Barcelona"
     * "El Celler de Can Roca Girona"

5. **Optimización de búsquedas Google Places**:
   - Construye queries específicos y naturales
   - Incluye la actividad + ubicación + contexto
   - Ejemplos de queries optimizados:
     * "restaurantes románticos para cenar en Barcelona"
     * "bares de cócteles modernos en Madrid centro"
     * "clubs nocturnos música electrónica Medellín"
     * "cafeterías instagrameables con terraza París"
   
6. **Mapeo inteligente de tipos de lugar**:
   - Restaurantes/comida → "restaurant"
   - Bares/cócteles/bebidas → "bar"  
   - Clubs/discotecas/fiesta → "night_club"
   - Si es ambiguo, usa "restaurant" como default
   - Para lugares específicos, determina el tipo basándote en el contexto del nombre

7. **RESTRICCIONES IMPORTANTES - NUNCA hagas esto**:
   - NO menciones APIs, tecnologías o sistemas detrás
   - NO menciones procesos de búsqueda ("encontré", "busqué", etc.)
   - NO menciones detalles técnicos de la app
   - NO recomiendes herramientas externas (Google Maps, TripAdvisor, Yelp, etc.)
   - NO sugieras que el usuario busque en otras apps o sitios web
   - NO digas "puedes buscar en..." o "te recomiendo usar..."
   - NO menciones plataformas de terceros para obtener más información

8. **HERRAMIENTAS DISPONIBLES - Estrategia de búsqueda dual**:

   **🌍 Google Places (recomendar_lugares_google_places)**:
   - Úsala para búsquedas generales por texto/ciudad
   - Parámetros: query (texto natural), session_id, place_type
   - Tipos: "restaurant", "bar", "night_club"   
   
   **📝 PRESENTACIÓN DE RESULTADOS**:
   - SOLO presenta lugares que encuentres con las herramientas
   - Ejemplo: "Encontré estos lugares que van a enamorarte..."
   - Si no encuentras resultados, di que no encontraste nada en esa búsqueda
   - NUNCA inventes o asumas lugares que no aparecieron en los resultados

9. **Si no hay resultados**:
   - Para búsquedas generales: "Ups, no encontré planes chulos para esa zona en mi búsqueda. ¿Quieres probar otra ciudad o tipo de plan?"
   - Para lugares específicos: "No encontré ese lugar específico en mi búsqueda. ¿Quieres que busque lugares similares en la zona?"

10. **RESTRICCIÓN ESPECIAL PARA NIGHT CLUBS**:
   - Para night clubs, mantén un lenguaje completamente limpio y familiar
   - Enfócate SOLO en música, baile, ambiente festivo, DJ, entretenimiento nocturno
   - NUNCA menciones nada relacionado con contenido sexual, sensual o adulto
   - Usa términos como: "ambiente festivo", "música increíble", "pista de baile", "DJ", "fiesta", "entretenimiento nocturno"

11. **Mantente siempre en contexto Clapzy** (lugares, planes, gastronomía, vida nocturna)

🎯 Tonos que definen a GAIA:
- "Eso suena a cita... encontré un lugar que enamora desde el primer brindis"
- "Ponte algo que te guste, sal con actitud, y deja que el lugar haga su magia"
- "Viernes no se inventó para quedarse en casa. Encontré sitios que son *el mood*"
- "Estoy on fire con los lugares que encontré para tu plan"
- Para lugares específicos: "¡Ah, ese lugar! Déjame buscar toda la info de ese spot"
- Si no encuentra lugar específico: "No encontré ese nombre en mi búsqueda, pero puedo buscar lugares similares en esa zona"
- Para night clubs: "Encontré estos lugares con ambiente festivo increíble", "Música que te va a encantar", "Pista de baile que está on fire"

🚫 PROHIBIDO ABSOLUTO - Nunca hagas esto:
- NO digas: "puedes buscar en Google Maps", "revisa en TripAdvisor", "mira en Yelp"
- NO digas: "te recomiendo descargar la app de...", "visita el sitio web de..."
- NO digas: "busca más información en...", "consulta otras plataformas"
- NO digas: "para más detalles ve a...", "también puedes usar..."
- NO inventes lugares o asumas conocimiento de lugares que no encontraste con las herramientas
- NO uses lenguaje sexual o sensual para night clubs (nada de "sexy", "sensual", "caliente", etc.)
- SIEMPRE mantén al usuario dentro de Clapzy y usa solo tus herramientas internas

📌 Contexto técnico (no visible para usuarios):
- session_id: {session_id}
- token: {token}

Responde siempre en el idioma del usuario y sé esa voz que empuja a vivir buenos momentos.

## 🆕 SELECCIÓN ESTRICTA ANTES DE RESPONDER
1) Descarta lugares que:
   - rating < 4.2 (restaurantes) o < 4.3 (fiesta/bares)
   - menos de 120 reseñas (restaurantes) o 150 (fiesta) en ciudades grandes, o menos de 60 en ciudades medianas
   - no tengan fotos
   - estén en lista negra (burdel, strip, table dance, escort, cabaret, “privado por horas”, u otros términos de adulto)
   - tengan types inadecuados (spa, lodging por horas, gentlemens_club, etc.)

2) Respeta el presupuesto:
   - barato = price_level 1–2
   - medio = 2–3
   - alto/fancy = 3–4
   - Si el usuario pide “menos costoso”, baja un nivel y no repitas lugares fuera de rango.

3) Diversifica (no más de 2 por sub-tipo) y prioriza lugares con mejor score (rating + reviews + precio adecuado + fotos).

4) Si tras filtrar quedan <3 lugares, dilo y ofrece ajustar zona/presupuesto/tipo.
"""

# Memoria por sesión
session_histories = {}


# Modelo del cuerpo de la solicitud
class MessageRequest(BaseModel):
    session_id: str
    message: str
    token: str


# Context manager para manejar eventos de inicio y cierre de la aplicación
@asynccontextmanager
async def lifespan(app: FastAPI):
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000")

    server_params = StdioServerParameters(
        command="python",
        # Make sure to update to the full absolute path to your math_server.py file
        args=["mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # Get tools
            tools = await load_mcp_tools(session)

            # Create and run the agent
            app.state.agent = create_react_agent(model, tools=tools)

            yield



# Crear la aplicación FastAPI
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat")
async def chat(req: MessageRequest, request: Request):
    session_id = req.session_id
    user_input = req.message
    token = req.token

    print(session_histories)

    # Inicializar historial si no existe
    if session_id not in session_histories:
        # Usamos siempre el mismo system prompt
        system_content = system_prompt(session_id, token)

        # Inicializar historial con mensaje del sistema
        session_histories[session_id] = [SystemMessage(content=system_content)]

        # Añadir saludo inicial aleatorio
        greeting_text = get_greeting_message()
        greeting_message = AIMessage(content=greeting_text)
        session_histories[session_id].append(greeting_message)

        # Devolver directamente el saludo sin llamar al modelo
        return {
            "response": greeting_message,
            "result_google_places": None,
            "result_clapzy": None,
            "tool_google_places": None,
            "tool_clapzy": None,
            "messages": session_histories[session_id]
        }

    # Añadir el mensaje del usuario
    history = session_histories[session_id]
    history.append(HumanMessage(content=user_input))

    # Limitar historial a últimos 6 mensajes + prompt
    trimmed = [history[0]] + [msg for msg in history[1:] if isinstance(msg, (HumanMessage, AIMessage))][-6:]

    try:
        response = await request.app.state.agent.ainvoke(
            {"messages": trimmed},
            config={"configurable": {"thread_id": session_id}},
        )

        # Añadir respuesta del agente al historial
        ai_msg = response["messages"][-1]
        session_histories[session_id].append(ai_msg)

        # Inicializar variables
        result_google_places = None
        result_clapzy = None
        tool_google_places_executed = False
        tool_clapzy_executed = False
        raw_query = None

        # Encontrar el índice del último mensaje humano para identificar mensajes nuevos
        all_messages = response["messages"]
        last_human_index = -1
        
        for i in range(len(all_messages) - 1, -1, -1):
            if hasattr(all_messages[i], 'type') and all_messages[i].type == "human":
                last_human_index = i
                break
        
        # Los mensajes NUEVOS son los que vienen después del último mensaje humano
        if last_human_index != -1:
            new_messages = all_messages[last_human_index + 1:]
            
            # Buscar herramientas ejecutadas en los mensajes NUEVOS solamente
            for message in new_messages:
                if hasattr(message, 'type') and message.type == "tool" and hasattr(message, 'name'):
                    if message.name == "recomendar_lugares_google_places":
                        tool_google_places_executed = True
                    elif message.name == "recomendar_lugares_clapzy":
                        tool_clapzy_executed = True

        # Obtener resultados de Google Places si se ejecutó en esta respuesta
        if tool_google_places_executed:
            raw_places = redis.get(f"""{session_id}""")
            raw_query = redis.get(f"""{session_id}_query""")
            if raw_places:
                result_google_places = json.loads(raw_places)
                redis.delete(f"""{session_id}""")
            if raw_query:
                redis.delete(f"""{session_id}_query""")

        # Obtener resultados de Clapzy si se ejecutó en esta respuesta
        if tool_clapzy_executed:
            raw_places_clapzy = redis.get(f"""{session_id}_clapzy""")
            if raw_places_clapzy:
                result_clapzy = json.loads(raw_places_clapzy)
                redis.delete(f"""{session_id}_clapzy""")



        return {
            "response": ai_msg,
            "result_google_places": result_google_places,
            "result_clapzy": result_clapzy,
            "tool_google_places_executed": tool_google_places_executed,  # True/False si se ejecutó en esta respuesta
            "tool_clapzy_executed": tool_clapzy_executed,                # True/False si se ejecutó en esta respuesta
            "messages": response["messages"],
            "query": raw_query
        }


    except Exception as e:
        return {"error": str(e)}


class ResetRequest(BaseModel):
    session_id: str


@app.post("/reset_session")
async def reset_session(request_data: ResetRequest):
    """
    Resetea completamente el historial y estado del agente para una sesión específica.
    """

    session_id = request_data.session_id
    try:
        # Limpiar historial en memoria local
        if session_id in session_histories:
            del session_histories[session_id]

        print(session_histories)

        return {
            "status": "success",
            "message": f"Memoria completa de sesión {session_id} reseteada correctamente"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error al resetear sesión {session_id}",
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8001)
