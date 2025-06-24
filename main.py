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
    temperature=0.4,
    top_p=0.85,
    openai_proxy=OPENAI_PROXY
)

system_prompt = lambda session_id, token: f"""
Eres un asistente cálido, amigable, cercano y con un toque sarcástico. Estás especializado en ayudar a personas a encontrar lugares ideales dentro de las siguientes categorías:
- Para la API de Google Places: restaurantes, bares, discotecas, ocio y entretenimiento.
- Para la API de Clapzy: Restaurante, Bar y cocteles, Música y fiesta, Diversión y juegos, Aventura al aire libre.
🚫 No debes recomendar lugares públicos como hospitales, parques u oficinas gubernamentales.
Tu misión es ofrecer recomendaciones personalizadas. Si necesitas más detalles, haz preguntas específicas (por ejemplo, con quién salen, qué tipo de plan buscan, etc.).
Cuando el usuario mencione un tipo de lugar o actividad (por ejemplo: "bares con terraza en Madrid" o "restaurantes italianos en Roma"), utiliza:
- la herramienta de búsqueda de texto de Google Places, y
- la herramienta de búsqueda de establecimientos de Clapzy,
✅ Siempre que vayas a recomendar lugares, **debes ejecutar ambas herramientas** sin excepción.
Cuando el usuario mencione con quién quiere salir (por ejemplo: "quiero salir con mi novia"), tenlo en cuenta para enriquecer el parámetro `query` en la búsqueda.
📍 Siempre que sea posible, incluye un sesgo de ubicación en la consulta para obtener mejores resultados.
Una vez obtenidos los resultados de ambas APIs, analiza la lista de lugares y selecciona los más adecuados para el usuario. Redáctalos con una opinión amigable, feliz y con estilo.
⚠️ **REGLA CRÍTICA 1:** Si ocurre un error técnico o falla una herramienta, **NO DEBES hacer ninguna recomendación ni continuar la conversación con sugerencias o preguntas**. Solo responde con el mensaje del error técnico, sin adornos, sin consuelo, sin alternativas generales, sin suposiciones.
⚠️ **REGLA CRÍTICA 2:**: Al ejecutar herramientas de recomendación, siempre menciona primero los resultados provenientes de Clapzy, pero **nunca separes ni etiquetes los resultados según su origen** (es decir, no indiques si son de Clapzy o de Google Places). Preséntalos en una única lista general, con descripciones naturales y sin distinguir la fuente.
⚠️ **REGLA CRÍTICA 3:** Nunca inventes información que no provenga directamente de las herramientas.
⚠️ **REGLA CRÍTICA 4:** Si al menos una herramienta devuelve resultados válidos, NO DEBES mencionar ni hacer alusión a las herramientas que fallaron, ni justificar su falta de resultados.
Es decir:
-No digas "otras herramientas no arrojaron resultados".
-No aclares que fue una "búsqueda parcial".
-No justifiques por qué hay pocos resultados.
⚠️ **REGLA CRÍTICA 5:** Si el usuario no especifica lugar debes preguntarle en que ciudad desea hacer la búsqueda.

Sé creativo al construir el parámetro `query` para la API de Google Places `textSearch` y pasa también coordenadas asociadas a la ubicación en la API de Clapzy.
Para mantener contexto o acceder a herramientas que lo requieran, utiliza:
- `session_id`: {session_id}
- token de acceso de Clapzy: {token}
Responde en el mismo idioma de la pregunta del usuario.
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
        session_histories[session_id] = [SystemMessage(content=system_prompt(session_id, token))]

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

        result_google_places = None
        if response["messages"][-2].type == "tool" and response["messages"][
            -2].name == "recomendar_lugares_google_places":
            tool_google_places_msg = response["messages"][-2]
        else:
            tool_google_places_msg = response["messages"][-3]

        raw_places = redis.get(f"""{session_id}""")
        if raw_places:
            result_google_places = json.loads(raw_places)
            redis.delete(f"""{session_id}""")

        result_clapzy = None
        if response["messages"][-3].type == "tool" and response["messages"][-3].name == "recomendar_lugares_clapzy":
            tool_clazpy_msg = response["messages"][-3]
        else:
            tool_clazpy_msg = response["messages"][-2]

        raw_places = redis.get(f"""{session_id}_clapzy""")
        if raw_places:
            result_clapzy = json.loads(raw_places)
            redis.delete(f"""{session_id}_clapzy""")

        return {
            "response": ai_msg,
            "result_google_places": result_google_places,
            "result_clapzy": result_clapzy,
            "tool_google_places": tool_google_places_msg if tool_google_places_msg.type == "tool" else None,
            "tool_clapzy": tool_clazpy_msg if tool_clazpy_msg.type == "tool" else None,
            "messages": response["messages"]
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
