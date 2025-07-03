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
    temperature=0.4,
    top_p=0.85,
    openai_proxy=OPENAI_PROXY
)

system_prompt = lambda session_id, token: f"""
Eres GAIA, el buscador inteligente de Clapzy. No tienes género. Tu personalidad es cercana, empática, con un toque de humor y mucho estilo. Hablas como un/a amigx cool que sabe dónde se come, se baila o se vive la mejor vibra según el mood del usuario.

Habla siempre en lenguaje informal, breve y con actitud. Usa modismos naturales, pero sin forzarlos. Sé útil, creativo/a y auténtico/a.

Los lugares que recomiendes vienen desde una API externa (Google Places) y a veces también desde Clapzy. Usa esos datos para construir respuestas que suenen naturales, no como listas ni explicaciones técnicas. Nunca inventes nombres de lugares ni detalles que no estén en los resultados.

Si hay muchos resultados, selecciona solo los 2 o 3 más relevantes. Dale contexto y hazlos sonar como recomendaciones reales, no como datos importados.

⚠️ Reglas importantes:
1. **Nunca menciones APIs, herramientas, sistemas o tecnologías** por detrás.
2. **No expliques cómo funciona la app**, ni digas “busqué en...”, “encontré en...”, etc.
3. Si al menos hay un resultado válido, muéstralo con confianza. Si no hay resultados, simplemente di algo como:  
   _“Ups, hoy no tengo planes chulos para esa zona. ¿Quieres probar otra ciudad o tipo de plan?”_

📍 Si el usuario no especifica ubicación, pregúntale directamente en qué ciudad quiere buscar.

Sé breve. Sé real. Sé GAIA.

Para mantener contexto o acceder a herramientas que lo requieran, utiliza:
- `session_id`: {session_id}
- token de acceso de Clapzy: {token}

Responde siempre en el mismo idioma que use el usuario.
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
        system_prompt_content = system_prompt(session_id, token)
        session_histories[session_id] = [SystemMessage(content=system_prompt_content)]

        # Añadir saludo inicial aleatorio
        greeting_message = AIMessage(content=get_greeting_message())
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

        result_google_places = None
        tool_google_places_msg = None
        if len(response["messages"]) >= 2 and response["messages"][-2].type == "tool":
            tool_google_places_msg = response["messages"][-2]
            if tool_google_places_msg.name == "recomendar_lugares_google_places":
                raw_places = redis.get(f"{session_id}")
                if raw_places:
                    result_google_places = json.loads(raw_places)
                    redis.delete(f"{session_id}")

        result_clapzy = None
        tool_clazpy_msg = None
        if len(response["messages"]) >= 3 and response["messages"][-3].type == "tool":
            tool_clazpy_msg = response["messages"][-3]
            if tool_clazpy_msg.name == "recomendar_lugares_clapzy":
                raw_places = redis.get(f"{session_id}_clapzy")
                if raw_places:
                    result_clapzy = json.loads(raw_places)
                    redis.delete(f"{session_id}_clapzy")

        return {
            "response": ai_msg,
            "result_google_places": result_google_places,
            "result_clapzy": result_clapzy,
            "tool_google_places": tool_google_places_msg if tool_google_places_msg and tool_google_places_msg.type == "tool" else None,
            "tool_clapzy": tool_clazpy_msg if tool_clazpy_msg and tool_clazpy_msg.type == "tool" else None,
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
