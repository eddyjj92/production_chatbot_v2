import json
import logging
from typing import Any, Union, List

from mcp.server.fastmcp import FastMCP
import requests
from pydantic import Field
import uuid
from dotenv import load_dotenv
import os
from redis import Redis

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
DEVELOPMENT = os.getenv("DEVELOPMENT")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Conexión a Redis con manejo de errores
try:
    redis = Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
    redis.ping()
    logger.info("✅ Redis conectado correctamente")
except Exception as e:
    logger.error(f"❌ Error conectando Redis: {e}")
    redis = None

#if DEVELOPMENT == 'True':
    # Configuración de proxy si es necesario
    # os.environ['HTTP_PROXY'] = 'http://localhost:5000'
    # bos.environ['HTTPS_PROXY'] = 'http://localhost:5000'

mcp = FastMCP("mcp")


@mcp.tool()
def recomendar_lugares_google_places(
    query: str = Field(
        description=(
            "Query optimizado para Google Places que incluye el tipo de lugar, ubicación y contexto específico. "
            "DEBE ser específico y natural. Ejemplos correctos: "
            "'restaurantes románticos para cenar en Barcelona', "
            "'bares de cócteles modernos en Madrid centro', "
            "'clubs nocturnos música electrónica en Medellín'. "
            "EVITAR queries genéricos como 'lugares en Barcelona'."
        )
    ),
    session_id: str = Field(
        description="ID de sesión para almacenar resultados en Redis"
    ),
    place_type: str = Field(
        description=(
            "Tipo específico de lugar para filtrar resultados. Opciones válidas: "
            "'restaurant' (para restaurantes, cafeterías, comida), "
            "'bar' (para bares, pubs, cócteles), "
            "'night_club' (para discotecas, clubs nocturnos, vida nocturna)"
        )
    ),
) -> Union[str, List[str], List[Any]]:
    """
    Realiza una búsqueda de lugares basada en la consulta proporcionada por el usuario,
    utilizando la API de Google Places Text Search, y devuelve una lista de nombres de lugares encontrados.

    Parámetros:
    - query (str): Cadena de texto que describe la intención del usuario, incluyendo
      el tipo de lugar, actividad, compañía y ubicación. Esta consulta se utiliza directamente
      como 'textQuery' en la solicitud a la API de Google Places Text Search.
    - session_id (str): Cadena de texto para usar como clave en la base de datos de redis.
    - place_type (str): Cadena de texto para clasificar lugar a buscar puede ser una de estas opciones: (restaurant, bar, night_club)

    Retorna:
    - Una lista de nombres de lugares encontrados que coinciden con la consulta del usuario.
    - Un mensaje de error si la solicitud a la API falla o si no se encuentran lugares que coincidan.
    """

    # print(f"""Query: {query}""")
    # print(f"""Session_id: {session_id}""")
    # print(f"""Place type: {place_type}""")

    # Definir el cuerpo de la solicitud optimizado
    cuerpo = {
        "textQuery": query,
        "pageSize": 20,
    }

    # Encabezados de la solicitud con campos optimizados
    encabezados = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        'X-Goog-FieldMask': (
            'places.displayName,'
            'places.formattedAddress,'
            'places.location,'
            'places.types,'
            'places.rating,'
            'places.userRatingCount,'
            'places.priceLevel,'
            'places.id,'
            'places.photos,'
            'places.regularOpeningHours.weekdayDescriptions,'
            'places.editorialSummary,'
            'places.internationalPhoneNumber,'
            'places.websiteUri,'
            'places.primaryType,'
            'places.shortFormattedAddress,'
            'places.businessStatus'
        ),
    }

    # Realizar la solicitud POST
    respuesta = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        json=cuerpo,
        headers=encabezados
    )

    # Verificar si la solicitud fue exitosa
    if respuesta.status_code != 200:
        print(f"Error en la solicitud: {respuesta.status_code} - {respuesta.text}")
        return f"Error en la solicitud: {respuesta.status_code} - {respuesta.text}"

    datos = respuesta.json()
    # print(f"""Datos: {datos}""")

    # Obtener los nombres de los lugares encontrados
    nombres_lugares = [lugar["displayName"]["text"] for lugar in datos["places"]]

    # Guardar en Redis con manejo de errores
    if redis is not None:
        try:
            redis.set(session_id, json.dumps(datos["places"]), ex=3600)
            redis.set(f"""{session_id}_query""", query, ex=3600)
            logger.info(f"💾 Datos de Google Places guardados en Redis correctamente")
        except Exception as e:
            logger.error(f"❌ Error al guardar Google Places en Redis: {e}")
    else:
        logger.warning("⚠️ Redis no disponible para Google Places")

    logger.info(f"✅ Google Places completado: {len(nombres_lugares)} lugares encontrados")
    return nombres_lugares


@mcp.tool()
def verificar_ciudades_clapzy(
    ciudad: str = Field(
        description="Nombre de la ciudad a verificar"
    ),
    lista_ciudades: List[str] = Field(
        default = ["Quito", "Bogotá", "Medellín", "Cali"],
        description="Lista de nombres de ciudades donde Clapzy maneja establecimientos"
    ),
    case_sensitive: bool = Field(
        default=False,
        description="Si la comparación debe ser sensible a mayúsculas/minúsculas (por defecto: False)"
    )
) -> dict:
    """
    Verifica si una ciudad específica está presente en una lista de ciudades válidas.

    Parámetros:
    - ciudad (str): Nombre de la ciudad a verificar.
    - lista_ciudades (List[str]): Lista de nombres de ciudades válidas contra las cuales verificar.
    - case_sensitive (bool): Si es True, la comparación será sensible a mayúsculas/minúsculas.
                            Si es False (por defecto), la comparación será insensible a mayúsculas/minúsculas.

    Retorna:
    - dict: Diccionario con la siguiente estructura:
        {
            "ciudad_verificada": str,  # La ciudad que se verificó
            "encontrada": bool,        # True si la ciudad está en la lista, False en caso contrario
            "ciudad_exacta": str,      # El nombre exacto de la ciudad encontrada en la lista (si aplica)
            "total_ciudades": int      # Total de ciudades en la lista de verificación
        }
    """

    # Validar entrada
    if not ciudad or not ciudad.strip():
        return {
            "ciudad_verificada": ciudad,
            "encontrada": False,
            "ciudad_exacta": None,
            "total_ciudades": len(lista_ciudades),
            "error": "El nombre de la ciudad no puede estar vacío"
        }

    ciudad_limpia = ciudad.strip()

    # Realizar la búsqueda
    encontrada = False
    ciudad_exacta = None

    if case_sensitive:
        # Búsqueda sensible a mayúsculas/minúsculas
        if ciudad_limpia in lista_ciudades:
            encontrada = True
            ciudad_exacta = ciudad_limpia
    else:
        # Búsqueda insensible a mayúsculas/minúsculas
        ciudad_lower = ciudad_limpia.lower()
        for ciudad_lista in lista_ciudades:
            if ciudad_lista.lower() == ciudad_lower:
                encontrada = True
                ciudad_exacta = ciudad_lista
                break

    return {
        "ciudad_verificada": ciudad_limpia,
        "encontrada": encontrada,
        "ciudad_exacta": ciudad_exacta,
        "total_ciudades": len(lista_ciudades)
    }


@mcp.tool()
def buscar_establecimientos_clapzy_por_ciudad(
    city: str = Field(description="Nombre de la ciudad donde buscar establecimientos."),
    session_id: str = Field(description="Clave para la base de datos de redis"),
    establishment_type: str = Field(description="Tipo de establecimiento"),
    token: str = Field(description="Token de acceso"),
    page: int = Field(default=1, description="Número de página"),
    limit: int = Field(default=10, description="Número máximo de resultados")
) -> Union[str, List[str], List[Any]]:
    """
    Realiza una búsqueda de establecimientos en una ciudad específica utilizando la API de Clapzy
    y devuelve una lista de nombres de lugares encontrados.
    """

    logger.info(f"🚀 === INICIANDO buscar_establecimientos_clapzy_por_ciudad ===")
    logger.info(f"🏙️  Ciudad: {city}")
    logger.info(f"🔑 Session_id: {session_id}")
    logger.info(f"🏪 Tipo establecimiento: {establishment_type}")
    logger.info(f"📄 Page: {page}, Limit: {limit}")

    # Parámetros de la solicitud
    params = {
        "city": city,
        "establishment_type": establishment_type,
        "page": page,
        "limit": limit
    }

    # Cabeceras comunes
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Endpoint base
    url = "https://backend.clapzy.pro/api/establishments/search_by_city"

    # Si token y session_id coinciden, usamos modo invitado
    if token == session_id:
        headers["X-Guest-Access-Token"] = token
        url = "https://backend.clapzy.pro/api/guest/establishments/search_by_city"
        logger.info("🎫 Usando modo INVITADO")
    else:
        headers["Authorization"] = f"Bearer {token}"
        logger.info("🎫 Usando modo AUTENTICADO")
    
    logger.info(f"🌐 URL a llamar: {url}")
    logger.info(f"📋 Parámetros: {params}")

    try:
        logger.info("🔄 Realizando solicitud HTTP...")
        respuesta = requests.get(url, params=params, headers=headers, timeout=30)
        logger.info(f"✅ Respuesta recibida con status: {respuesta.status_code}")
        respuesta.raise_for_status()
    except requests.exceptions.Timeout as e:
        logger.error(f"⏰ TIMEOUT: {e}")
        return f"Error: Timeout al conectar con la API de Clapzy - {e}"
    except requests.exceptions.ConnectionError as e:
        logger.error(f"🔌 CONNECTION ERROR: {e}")
        return f"Error: No se pudo conectar con la API de Clapzy - {e}"
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ HTTP ERROR: {respuesta.status_code} - {e}")
        return f"Error HTTP en la API de Clapzy: {respuesta.status_code} - {e}"
    except requests.exceptions.RequestException as e:
        logger.error(f"🚨 REQUEST ERROR: {e}")
        return f"Error general en la solicitud: {e}"

    try:
        datos = respuesta.json()
        logger.info(f"📊 Datos JSON parseados correctamente. Claves: {list(datos.keys())}")
    except json.JSONDecodeError as e:
        logger.error(f"📄 ERROR JSON: {e}")
        return f"Error: La API devolvió una respuesta que no es JSON válido - {e}"

    establecimientos = []
    if "establishments" in datos:
        est_obj = datos["establishments"]
        logger.info(f"🏪 Establishments encontrado, tipo: {type(est_obj)}")
        # Si Clapzy devuelve un objeto paginado, el array está en la clave 'data'
        if isinstance(est_obj, dict) and "data" in est_obj:
            establecimientos = est_obj["data"]
            logger.info(f"📄 Usando estructura paginada, {len(establecimientos)} establecimientos")
        else:
            establecimientos = est_obj
            logger.info(f"🏪 Usando estructura directa, {len(establecimientos)} establecimientos")
    elif "data" in datos:
        establecimientos = datos["data"]
        logger.info(f"📄 Usando clave 'data', {len(establecimientos)} establecimientos")
    else:
        logger.warning("❓ No se encontró estructura de datos conocida")

    try:
        nombres_lugares = [lugar.get("name", "Sin nombre") for lugar in establecimientos if isinstance(lugar, dict)]
        logger.info(f"📋 Procesados {len(nombres_lugares)} nombres de lugares")
    except Exception as e:
        logger.error(f"🔥 ERROR procesando nombres: {e}")
        return f"Error al procesar nombres de lugares: {e}"

    # Guardar los establecimientos en Redis
    if redis is not None:
        try:
            redis.set(f"{session_id}_clapzy", json.dumps(establecimientos), ex=3600)
            logger.info(f"💾 Datos guardados en Redis correctamente")
        except Exception as e:
            logger.error(f"❌ Error al guardar en Redis: {e}")
            # No retornar error aquí, continuar con la respuesta
    else:
        logger.warning("⚠️ Redis no disponible, no se pueden guardar datos")

    if not nombres_lugares:
        logger.warning(f"🚫 No se encontraron establecimientos")
        return f"No se encontraron establecimientos de tipo '{establishment_type}' en la ciudad de {city}"

    logger.info(f"✅ === COMPLETADO: {len(nombres_lugares)} establecimientos encontrados ===")
    return nombres_lugares



@mcp.tool()
def buscar_establecimientos_clapzy_por_coordenadas(
    latitude: str = Field(
        description=(
            "Latitud parte de las coordenadas asociadas al lugar donde el cliente desea salir"
        )
    ),
    longitude: str = Field(
        description=(
            "Longitud parte de las coordenadas asociadas al lugar donde el cliente desea salir"
        )
    ),
    session_id: str = Field(
            description=(
                "Cadena de texto para usar como clave en la base de datos de redis"
            )
        ),
    establishment_type: str = Field(
                description=(
                    "Cadena de texto para clasificar lugar a buscar puede ser una de estas opciones: ('Restaurante', 'Bar y cocteles', 'Música y fiesta', 'Diversión y juegos','Aventura al aire libre')"
                )
            ),
    token: str = Field(
                    description=(
                        "Token de acceso a la api de Clapzy"
                    )
                ),
) -> Union[str, List[str], List[Any]]:
    """
    Realiza una búsqueda de lugares basada en la consulta proporcionada por el usuario,
    utilizando la API de Clapzy, y devuelve una lista de nombres de lugares encontrados.

    Parámetros:
    - latitude (str): Latitud parte de las coordenadas asociadas al lugar donde el cliente desea salir ejemplo: 19.4326.
    - longitude (str): Longitud parte de las coordenadas asociadas al lugar donde el cliente desea salir ejemplo: -99.1332.
    - session_id (str): Cadena de texto para usar como clave en la base de datos de redis.
    - establishment_type (str): Cadena de texto para clasificar lugar a buscar puede ser una de estas opciones: ('Restaurante', 'Bar y cocteles', 'Música y fiesta', 'Diversión y juegos','Aventura al aire libre').
    - token (str): Token de acceso a la api de Clapzy.

    Retorna:
    - Una lista de nombres de lugares encontrados que coinciden con la consulta del usuario.
    - Un mensaje de error si la solicitud a la API falla o si no se encuentran lugares que coincidan.
    """

    logger.info(f"🌍 === INICIANDO buscar_establecimientos_clapzy_por_coordenadas ===")
    logger.info(f"📍 Latitud: {latitude}")
    logger.info(f"📍 Longitud: {longitude}")
    logger.info(f"🔑 Session_id: {session_id}")
    logger.info(f"🏪 Tipo establecimiento: {establishment_type}")

    # Definir el cuerpo de la solicitud
    cuerpo = {
        "latitude": latitude,
        "longitude": longitude,
        "establishment_type": establishment_type,
        "radius": 50
    }

    # Encabezados de la solicitud
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    url = "https://backend.clapzy.pro/api/establishments/coordenates"

    if token == session_id:
        headers["X-Guest-Access-Token"] = token
        del headers["Authorization"]
        url = "https://backend.clapzy.pro/api/guest/establishments/coordenates"
        logger.info("🎫 Usando modo INVITADO (coordenadas)")
    else:
        logger.info("🎫 Usando modo AUTENTICADO (coordenadas)")
    
    logger.info(f"🌐 URL a llamar: {url}")
    logger.info(f"📋 Parámetros: {cuerpo}")

    try:
        logger.info("🔄 Realizando solicitud HTTP (coordenadas)...")
        respuesta = requests.get(url, params=cuerpo, headers=headers, timeout=30)
        logger.info(f"✅ Respuesta recibida con status: {respuesta.status_code}")
        respuesta.raise_for_status()
    except requests.exceptions.Timeout as e:
        logger.error(f"⏰ TIMEOUT (coordenadas): {e}")
        return f"Error: Timeout al conectar con la API de Clapzy - {e}"
    except requests.exceptions.ConnectionError as e:
        logger.error(f"🔌 CONNECTION ERROR (coordenadas): {e}")
        return f"Error: No se pudo conectar con la API de Clapzy - {e}"
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ HTTP ERROR (coordenadas): {respuesta.status_code} - {e}")
        return f"Error HTTP en la API de Clapzy: {respuesta.status_code} - {e}"
    except requests.exceptions.RequestException as e:
        logger.error(f"🚨 REQUEST ERROR (coordenadas): {e}")
        return f"Error general en la solicitud: {e}"

    try:
        datos = respuesta.json()
        logger.info(f"📊 Datos JSON parseados correctamente (coordenadas). Claves: {list(datos.keys())}")
    except json.JSONDecodeError as e:
        logger.error(f"📄 ERROR JSON (coordenadas): {e}")
        return f"Error: La API devolvió una respuesta que no es JSON válido - {e}"

    # Verificar estructura y obtener establecimientos
    if "establishments" not in datos:
        logger.error("❌ No se encontró clave 'establishments' en respuesta (coordenadas)")
        return "No se encontraron establecimientos en la respuesta de la API"
    
    establecimientos = datos["establishments"]
    logger.info(f"🏪 Establecimientos encontrados (coordenadas): {len(establecimientos)}")

    try:
        nombres_lugares = [lugar.get("name", "Sin nombre") for lugar in establecimientos if isinstance(lugar, dict)]
        logger.info(f"📋 Procesados {len(nombres_lugares)} nombres de lugares (coordenadas)")
    except Exception as e:
        logger.error(f"🔥 ERROR procesando nombres (coordenadas): {e}")
        return f"Error al procesar nombres de lugares: {e}"

    # Guardar en Redis
    if redis is not None:
        try:
            redis.set(f"""{session_id}_clapzy""", json.dumps(establecimientos), ex=3600)
            logger.info(f"💾 Datos guardados en Redis correctamente (coordenadas)")
        except Exception as e:
            logger.error(f"❌ Error al guardar en Redis (coordenadas): {e}")
            # No retornar error aquí, continuar con la respuesta
    else:
        logger.warning("⚠️ Redis no disponible (coordenadas)")

    if not nombres_lugares:
        logger.warning(f"🚫 No se encontraron establecimientos (coordenadas)")
        return f"No se encontraron establecimientos de tipo '{establishment_type}' en las coordenadas especificadas"

    logger.info(f"✅ === COMPLETADO (coordenadas): {len(nombres_lugares)} establecimientos encontrados ===")
    return nombres_lugares


if __name__ == "__main__":
    logger.info("🚀 === INICIANDO MCP SERVER ===")
    logger.info("📡 Transporte: STDIO")
    mcp.run(transport="stdio")
