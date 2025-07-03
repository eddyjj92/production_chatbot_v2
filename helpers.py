import random


def get_greeting_message():
    greetings = [
        "¡Hola! Bienvenido/a. ¿En qué puedo ayudarte hoy?",
        "¡Buen día! Estoy aquí para asistirte, ¿cómo puedo servirte?",
        "¡Bienvenido/a! Me alegra tenerte por aquí. ¿Qué necesitas?",
        "¿Listo/a para empezar? ¡Estoy aquí para ayudarte!",
        "¡Hola de nuevo! ¿En qué puedo colaborarte hoy?",
        "¡Muy buenas! Soy tu asistente virtual. ¿Qué puedo hacer por ti?",
        "¡Encantado/a de verte! Cuéntame, ¿en qué puedo ayudarte?",
        "¡Saludos! ¿Qué planes tienes para hoy? Yo estoy listo/a para ayudarte.",
        "¡Bienvenido/a! Si necesitas algo, solo dime.",
        "¡Hola! Estoy aquí para lo que necesites. ¿Por dónde empezamos?"
    ]
    return random.choice(greetings)
