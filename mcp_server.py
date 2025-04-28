import json
from typing import  Any

from mcp.server.fastmcp import FastMCP
import requests
from pydantic import Field
import uuid
from dotenv import load_dotenv
import os
from redis import Redis

# Conexión a Redis
redis = Redis(host='localhost', port=6379, db=0, decode_responses=True)

load_dotenv()
DEVELOPMENT = os.getenv("DEVELOPMENT")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

if DEVELOPMENT == 'True':
    # Configuración de proxy si es necesario
    os.environ['HTTP_PROXY'] = 'http://localhost:5000'
    os.environ['HTTPS_PROXY'] = 'http://localhost:5000'

mcp = FastMCP("mcp")


@mcp.tool()
def recomendar_lugares(
        area: str = Field(..., description="Área donde el usuario desea hacer la reserva."),
        categoria: str = Field(..., description="Categoría del lugar, por ejemplo, 'bar', 'restaurant', etc."),
) -> str | list[str] | list[Any]:
    """
    Realiza una búsqueda de lugares en una categoría específica dentro de un área determinada
    utilizando la API de Google Places y devuelve la información del primer resultado encontrado.
    """
    # Construir la consulta de texto
    consulta = f"{categoria} en {area}"

    # Definir el cuerpo de la solicitud
    cuerpo = {
        "textQuery": consulta,
        "includedType": categoria,
        "pageSize": 20
    }

    # Encabezados de la solicitud
    encabezados = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,  # Reemplaza con tu clave de API
        'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.types,places.rating,places.userRatingCount,places.priceLevel,places.id,places.photos,places.regularOpeningHours.weekdayDescriptions,places.editorialSummary',
    }

    # Realizar la solicitud POST
    respuesta = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        json=cuerpo,
        headers=encabezados
    )

    # Verificar si la solicitud fue exitosa
    if respuesta.status_code != 200:
        return f"Error en la solicitud: {respuesta.status_code} - {respuesta.text}"

    datos = respuesta.json()
    print(datos)

    # Verificar si se encontraron lugares
    if "places" not in datos or not datos["places"]:
        return f"No se encontraron lugares de tipo '{categoria}' en el área '{area}'."

    # Obtener el primer lugar encontrado
    lugar = datos["places"][0]
    nombre_lugar = lugar["displayName"]["text"]
    direccion = lugar.get("formattedAddress", "Dirección no disponible")

    # Generar un ID de reserva único
    id_reserva = uuid.uuid4()

    # Verificar si se encontraron lugares
    if "places" not in datos or not datos["places"]:
        return [f"No se encontraron lugares de tipo '{categoria}' en el área '{area}'."]

    # Obtener los nombres de los lugares encontrados
    nombres_lugares = [lugar["displayName"]["text"] for lugar in datos["places"]]

    redis.set('places', json.dumps(datos["places"]))

    return nombres_lugares


if __name__ == "__main__":
    mcp.run(transport="sse")
