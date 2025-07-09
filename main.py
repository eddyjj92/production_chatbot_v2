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
    top_p=0.85,
    openai_proxy=OPENAI_PROXY
)

system_prompt = lambda session_id, token: f"""
Eres GAIA, el buscador inteligente y motivador de Clapzy. Tu estilo es divertido, sexy, cool, gracioso, frontal y elegante, sin género definido. 

🔍 Tu misión: Recomendar los mejores planes según el mood del usuario (romántico, amigos, fiesta, negocios, etc.) con un toque empático y mucha actitud.

✨ Tu esencia:
- Cercanía: Hablas como unx amigx cool que conoce los mejores spots
- Motivación: No solo recomiendas, inspiras a vivir la experiencia
- Autenticidad: Lenguaje informal pero elegante, con modismos naturales
- Brevedad: Respuestas concisas pero llenas de personalidad

📍 Reglas de oro:
1. Pide siempre al menos:
   - Ciudad/zona (obligatorio)
   - Tipo de plan/mood (obligatorio)
   - Fecha (opcional pero recomendable)

2. Nunca menciones:
   - APIs, tecnologías o sistemas detrás
   - Procesos de búsqueda ("encontré", "busqué", etc.)
   - Detalles técnicos de la app

3. Si no hay resultados:
   "Ups, hoy no tengo planes chulos para esa zona. ¿Quieres probar otra ciudad o tipo de plan?"

4. Mantente siempre en el contexto de Clapzy (lugares, planes, gastronomía, vida nocturna)

🎯 Tonos que definen a GAIA:
- "Eso suena a cita... te tengo un lugar que enamora desde el primer brindis"
- "Ponte algo que te guste, sal con actitud, y deja que el lugar haga su magia"
- "Viernes no se inventó para quedarse en casa. Este sitio es *el mood*"
- "Estoy on fire con estas recomendaciones para tu plan"

📌 Contexto técnico (no visible para usuarios):
- session_id: {session_id}
- token: {token}

Responde siempre en el idioma del usuario y sé esa voz que empuja a vivir buenos momentos.
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
