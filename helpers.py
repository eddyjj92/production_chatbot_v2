import random


def get_greeting_message():
    greetings = [
        "**Hola soy Gaia.. ¿Qué mood traes hoy? Yo tengo el lugar perfecto para eso.** 😎",
        "**Hola soy Gaia.. Hoy no decides sol@, yo te acompaño en la búsqueda sagrada del plan ideal.** ✨",
        "**Hola soy Gaia.. Dime si estás para romance, caos, comida o todo lo anterior.** 🔥",
        "**Hola soy Gaia.. Ok, estoy ready. ¿Plan chill, plan intenso o plan que ni tú sabías que querías?** 😏",
        "**Hola soy Gaia.. No eres exigente… solo sabes lo que quieres. Dímelo y lo encuentro.** 💅",
        "**Hola soy Gaia.. ¿Quién necesita suerte cuando tienes a GAIA?** 🍀🤖",
        "**Hola soy Gaia.. Hoy salimos bien. Dame una pista y yo te doy el plan perfecto.** 🎯",
        "**Mood bajón, mood fiesta, mood sin rumbo… aquí todo tiene destino.** 💃",
        "**No prometo amor eterno, pero sí planes inolvidables.** ❤️‍🔥",
    ]
    return random.choice(greetings)
