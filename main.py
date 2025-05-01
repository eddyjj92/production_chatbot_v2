import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from contextlib import asynccontextmanager
from redis import Redis

# Cargar variables de entorno
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
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
    model="gpt-4o-mini",
    temperature=0.7,
    top_p=0.9,
    openai_proxy=OPENAI_PROXY
)

# Prompt inicial
system_prompt = lambda session_id: (f"""
Eres un asistente cálido, amigable, cercano y sarcástico, especializado en ayudar a personas a encontrar los lugares que se ajusten a estas categorias(restaurantes, bares, discotecas, ocio y entretenimiento), no puedes recomendar lugares publicos como (hospitales, parques, etc). 
Da recomendaciones personalizadas y haz preguntas si necesitas más detalles.
Cuando el usuario mencione un tipo de lugar o actividad (por ejemplo, "bares con terraza en Madrid" o "restaurantes italianos en Roma"), utiliza la herramienta de búsqueda de texto de la API de Google Places para encontrar lugares relevantes. 
Cuando el usuario mencione con quien quiere salir (por ejemplo, "quiero salir con mi novia"), tenlo en cuanta a la hora de pasar el parametro query en la herramienta de búsqueda de texto de la API de Google Places para encontrar lugares relevantes.
Realiza una solicitud a la API con el texto proporcionado por el usuario y, si es posible, incluye un sesgo de ubicación para mejorar la relevancia de los resultados.
Después de obtener los resultados, analiza la lista de lugares devueltos y selecciona los más adecuados para el usuario. Agrega una opinion amigable y feliz.
Si puedes usar herramientas para mejorar tus respuestas, hazlo con confianza.
Se breve en tus respuestas y no inventes informacion que no hallas obtenido de herramientas.
Se creativo a la hora de pasar el parametro 'query' a la api de google places textSearch.
Si detectas que existen problemas tecnicos en una tool no hagas recomendaciones, no hagas preguntas de restroalimentacion solo da el detalle del error.
Usa el session_id: {session_id} si te hace falta para una tool.
""")

# Memoria por sesión
session_histories = {}


# Modelo del cuerpo de la solicitud
class MessageRequest(BaseModel):
    session_id: str
    message: str


# Context manager para manejar eventos de inicio y cierre de la aplicación
@asynccontextmanager
async def lifespan(app: FastAPI):
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000")

    # Inicializar herramientas y agente
    app.state.client = await MultiServerMCPClient({
        "mcp": {
            # make sure you start your weather server on port 8000
            "url": f"{MCP_SERVER_URL}/sse",
            "transport": "sse"
        }
    }).__aenter__()

    tools = app.state.client.get_tools()
    memory = MemorySaver()
    app.state.agent = create_react_agent(model, tools=tools, checkpointer=memory)

    yield

    await app.state.client.__aexit__(None, None, None)


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

    # Inicializar historial si no existe
    if session_id not in session_histories:
        session_histories[session_id] = [SystemMessage(content=system_prompt(session_id))]

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

        result = None
        if response["messages"][-2].type == "tool" and response["messages"][-2].content:
            raw_places = redis.get(session_id)

            if raw_places:
                result = json.loads(raw_places)
                redis.delete(session_id)

        print(f"""Result: {result}""")

        return {
            "response": ai_msg.content,
            "result": result,
            "tool": response["messages"][-2]
        }


    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8001)
