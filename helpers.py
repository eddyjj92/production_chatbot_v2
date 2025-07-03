import random


def get_greeting_message():
    greetings = [
        "¡Hola hola! ¿Listo/a para descubrir planes chulos hoy?",
        "¿Qué tal? Soy GAIA, tu buscadora de vibes. ¿Buscás plan o ya tenés uno en mente?",
        "¡Bienvenido/a! Hoy vamos a encontrar el plan perfecto para vos.",
        "Hey hey 🖐️ Soy GAIA y estoy lista para recomendarte lo mejor de lo mejor. ¿Por dónde empezamos?",
        "¡Holi! ¿En qué puedo ayudarte a descubrir hoy? 🕵️‍♀️",
        "¡Saludos! Soy GAIA, tu asistente de planes increíbles. ¿Qué andás buscando?",
        "¡Buen día, viajero/a de bares y aventuras! ¿Te ayudo a encontrar algo genial?",
        "¡Bienvenido/a! Si buscas buenos planes, llegaste al lugar correcto 😉",
        "¿Y qué se te antoja hoy? Yo tengo buenas ideas. ¡Comencemos!",
        "¡Hola! Estoy acá para ayudarte a encontrar lugares y planes que no te vas a querer perder."
    ]
    return random.choice(greetings)
