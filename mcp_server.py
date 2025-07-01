import json
from typing import Any, Union, List

from mcp.server.fastmcp import FastMCP
import requests
from pydantic import Field
import uuid
from dotenv import load_dotenv
import os
from redis import Redis

load_dotenv()
DEVELOPMENT = os.getenv("DEVELOPMENT")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Conexión a Redis
redis = Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

if DEVELOPMENT == 'True':
    # Configuración de proxy si es necesario
    os.environ['HTTP_PROXY'] = 'http://localhost:5000'
    os.environ['HTTPS_PROXY'] = 'http://localhost:5000'

mcp = FastMCP("mcp")


@mcp.tool()
def recomendar_lugares_google_places(
    query: str = Field(
        description=(
            "Cadena de texto que describe la intención del usuario, incluyendo "
            "el tipo de lugar, actividad, compañía y ubicación. "
            "Por ejemplo: 'Quiero cenar sushi con mi pareja en Barcelona'. "
            "Esta consulta se utiliza directamente como 'textQuery' en la solicitud "
            "a la API de Google Places Text Search."
        )
    ),
    session_id: str = Field(
            description=(
                "Cadena de texto para usar como clave en la base de datos de redis"
            )
        ),
    place_type: str = Field(
                description=(
                    "Cadena de texto para clasificar lugar a buscar puede ser una de estas opciones: (restaurant, bar, night_club)"
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

    # Definir el cuerpo de la solicitud
    cuerpo = {
        "textQuery": query,
        "pageSize": 20,
        "includedType": place_type,
        "strictTypeFiltering": True
    }

    # Encabezados de la solicitud
    encabezados = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,  # Reemplaza con tu clave de API
        'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.types,places.rating,places.userRatingCount,places.priceLevel,places.id,places.photos,places.regularOpeningHours.weekdayDescriptions,places.editorialSummary,places.internationalPhoneNumber',
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

    redis.set(session_id, json.dumps(datos["places"]))

    return nombres_lugares


@mcp.tool()
def recomendar_lugares_clapzy(
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

    print(f"""Latitud: {latitude}""")
    print(f"""Longitud: {longitude}""")
    print(f"""Session_id: {session_id}""")
    print(f"""Establishment type: {establishment_type}""")

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

    # Realizar la solicitud POST
    respuesta = requests.get(
        url,
        params=cuerpo,
        headers=headers
    )

    # Verificar si la solicitud fue exitosa
    if respuesta.status_code != 200:
        print(f"Error en la solicitud: {respuesta.status_code} - {respuesta.text}")
        return f"Error en la solicitud: {respuesta.status_code} - {respuesta.text}"

    datos = respuesta.json()
    print(f"""Datos: {datos}""")

    # Obtener los nombres de los lugares encontrados
    nombres_lugares = [lugar["name"] for lugar in datos["establishments"]]

    redis.set(f"""{session_id}_clapzy""", json.dumps(datos["establishments"]))

    return nombres_lugares


if __name__ == "__main__":
    mcp.run(transport="stdio")
