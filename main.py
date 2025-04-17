import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from contextlib import asynccontextmanager


# Cargar variables de entorno
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEVELOPMENT = os.getenv("DEVELOPMENT")
openai_proxy = None

if DEVELOPMENT == 'True':
    openai_proxy = "http://localhost:5000"

# Configurar el modelo
model = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0,
    top_p=0.9,
    openai_proxy=openai_proxy
)

# Prompt inicial
system_prompt = """
Eres un asistente cálido y amigable, especializado en ayudar a personas a encontrar bares, restaurantes y lugares para salir.
Da recomendaciones personalizadas y haz preguntas si necesitas más detalles. 
Si puedes usar herramientas para mejorar tus respuestas, hazlo con confianza.
"""

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
            "url": MCP_SERVER_URL,
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


@app.post("/chat")
async def chat(req: MessageRequest, request: Request):
    session_id = req.session_id
    user_input = req.message

    # Inicializar historial si no existe
    if session_id not in session_histories:
        session_histories[session_id] = [SystemMessage(content=system_prompt)]

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

        return {"response": ai_msg.content}

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001)