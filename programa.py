from machine import Pin, ADC
import time
import rp2
import uasyncio as asyncio
import micro_monitoring

FAILED_ATTEMPTS_TOLERANCE = 3
"""Cantidad de intentos erróneos que el candado tolera."""
FAILED_ATTEMPTS_TIME_INTERVAL = 20
"""Los últimos N segundos en los que puede haber hasta `FAILED_ATTEMPTS_TOLERANCE` intentos erróneos."""
LED_BLINK_TIME = 0.2
"""Segundos que dura un instante en el que el LED parpadea."""
ALARM_DURATION_SECONDS = 5
"""Segundos que dura el estado de alarma."""
KEY_INPUT_TIME_LIMIT = 10
"""Segundos que persiste un input del tablero antes de restablecerse a nulo."""
LIGHT_THRESHOLD = 40_000
"""Valor digital máximo del sensor de iluminación aceptable."""


class Led():
    """Conjunto de los pines rojo, verde y azul del foco LED."""

    def __init__(self):
        """Inicializa los pines para cada color."""
        self.rojo = Pin(16, Pin.OUT)
        self.verde = Pin(17, Pin.OUT)
        self.azul = Pin(18, Pin.OUT)

    def set_off(self):
        """Apaga los tres colores del led."""
        self.rojo.off(), self.verde.off(), self.azul.off()

    def set_white(self):
        """Pone el LED de color blanco."""
        self.rojo.on(), self.verde.on(), self.azul.on()

    def set_red(self):
        """Pone el LED de color rojo."""
        self.rojo.on(), self.verde.off(), self.azul.off()

    def set_blue(self):
        """Pone el LED de color azul."""
        self.rojo.off(), self.verde.off(), self.azul.on()

    def set_green(self):
        """Pone el LED de color verde."""
        self.rojo.off(), self.verde.on(), self.azul.off()

    def blink(self):
        """Apaga el LED por un pequeño instante."""
        self.set_off()
        time.sleep(LED_BLINK_TIME)


class State:
    def __innit__(self):
        self.dia = True
        self.led = Led()
        self.alarma_activada = False
        self.inicio_alarma = 0
        self.candado = True
        self.boot_mode = True
        self.codigo_ingresado = ""
        self.intentos_fallidos = []

    def is_daylight(self):
        return self.dia

    async def is_alarmed(self):
        """Actualiza el estado alarmado, y controla si el tiempo de alarma ya terminó."""
        if not self.alarma_activada:
            return False

        if time.time() - self.inicio_alarma >= ALARM_DURATION_SECONDS:
            self.alarma_activada = False
            self.codigo_ingresado = ""
            self.intentos_fallidos = []
            print("Tiempo de alarma terminado. Alarma desactivada.")
            return False

    def is_locked(self):
        return self.candado

    def is_boot_mode(self):
        return self.boot_mode

    def to_locked(self):
        self.led.set_off()
        self.codigo_ingresado = ""
        self.boot_mode = False
        self.candado = True

    def to_boot_mode(self):
        self.boot_mode = True
        self.candado = True
        self.dia = True
        self.codigo_ingresado = ""
        print("Ingrese la nueva clave.")

    def to_unlocked(self):
        self.candado = False
        self.intentos_fallidos = 0

    def failed_attempt(self):
        """Procesar un intento fallido de desbloquear el candado. Dispara la alarma si es necesario."""
        self.led.set_red()
        self.time.sleep(0.2)

        attempt_time = time.time()
        self.intentos_fallidos.append(attempt_time)
        if len(self.intentos_fallidos) >= FAILED_ATTEMPTS_TOLERANCE:
            time_difference = attempt_time - self.intentos_fallidos[2]
            if time_difference < FAILED_ATTEMPTS_TIME_INTERVAL:
                # Disparar la alarma si hubo muchos intentos erróneos Y en poco tiempo.
                self.activar_alarma()

    def activar_alarma(self):
        print("¡ALERTA! Demasiados intentos fallidos. Activando alarma.")
        self.alarma_activada = True
        self.inicio_alarma = time.time()


state = State()

# Pines
led = Led()
sensor_pin = ADC(Pin(26))
key_names = "*7410852#963DCBA"


def get_pressed_keys(machine):
    """Obtiene las teclas ingresadas del tablero 4x4."""
    keys = machine.get()
    while machine.rx_fifo():
        keys = machine.get()

    pressed = []
    for i in range(len(key_names)):
        if (keys & (1 << i)):
            pressed.append(key_names[i])

    state.ultimo_ingreso_tiempo = time.time() if len(pressed) > 0 else 0

    return pressed


def oninput(machine):
    """Manejar la entrada de teclas."""

    if state.alarma_activada:
        print("Alarma activada. No se permiten nuevos inputs.")
        return

    pressed = get_pressed_keys(machine)

    if not state.is_daylight():
        print("No hay suficiente luz. Ignorando entrada de teclas.")
        return

    if state.candado and len(pressed) > 0 and pressed[0] == "#":
        print("Input reestablecido a nulo.", state.candado)
        state.codigo_ingresado = ""
        return

    if state.is_boot_mode() and len(pressed) > 0:
        state.codigo_ingresado += pressed[0]
        state.led.set_white()
        time.sleep(0.2)
        print("Clave:", state.codigo_ingresado)
        if len(state.codigo_ingresado) == 4:
            state.codigo_correcto = state.codigo_ingresado
            print("Código establecido: ", state.codigo_correcto)
            state.to_locked()

    if state.is_locked() and not state.is_daylight():
        print("Boop.")

    if state.is_locked() and state.is_daylight() and len(pressed) > 0:
        if (pressed[0] == "#"):
            print("Reiniciado el código ingresado")
            state.codigo_ingresado = ""
            return

        state.codigo_ingresado += pressed[0]
        print("Código ingresado hasta ahora:", state.codigo_ingresado)
        state.led.blink()

        # Control de codigo correcto
        if len(state.codigo_ingresado) == 4:
            if state.codigo_ingresado == state.codigo_correcto:
                print("Código correcto. Pasando a estado abierto.")
                state.to_unlocked()
            else:
                print("Código incorrecto. Reiniciando input.")
                state.failed_attempt()
            state.codigo_ingresado = ""
        return

    if len(pressed) > 0:
        state.codigo_ingresado += pressed[0]
        if pressed[0] == "*":
            print("Cerrando caja.")
            state.to_locked()
        if state.codigo_ingresado == "###":
            state.to_boot_mode()


@rp2.asm_pio(set_init=[rp2.PIO.IN_HIGH]*4)
def keypad():
    wrap_target()
    set(y, 0)                             # 0
    label("1")
    mov(isr, null)                        # 1
    set(pindirs, 1)                       # 2
    in_(pins, 4)                          # 3
    set(pindirs, 2)                       # 4
    in_(pins, 4)                          # 5
    set(pindirs, 4)                       # 6
    in_(pins, 4)                          # 7
    set(pindirs, 8)                       # 8
    in_(pins, 4)                          # 9
    mov(x, isr)                           # 10
    jmp(x_not_y, "13")                    # 11
    jmp("1")                              # 12
    label("13")
    push(block)                           # 13
    irq(0)
    mov(y, x)                             # 14
    jmp("1")                              # 15
    wrap()


def get_light_value():
    """Devuelve el valor (digital) medido por el sensor de iluminación."""
    return sensor_pin.read_u16()


async def operations():
    global alarma_activada, intentos_fallidos, led, dia

    for i in range(10, 14):
        Pin(i, Pin.IN, Pin.PULL_DOWN)

    sm = rp2.StateMachine(0, keypad, freq=2000, in_base=Pin(
        10, Pin.IN, Pin.PULL_DOWN), set_base=Pin(6))
    sm.active(1)
    sm.irq(oninput)
    print("Caja fuerte iniciada. Registre su clave: ")

    while True:
        valor_luz = get_light_value()
        if state.is_alarmed():
            # Estado alarmado.
            state.led.rojo.on()
            state.led.azul.off()
            await asyncio.sleep(LED_BLINK_TIME)
            state.led.rojo.off()
            state.led.azul.on()
            await asyncio.sleep(LED_BLINK_TIME)

        if state.is_boot_mode():
            # Estado inicialización.
            state.led.set_white()

        if state.is_locked():
            # Estado cerrado.
            if valor_luz > LIGHT_THRESHOLD:
                state.led.set_red()
                dia = False
                state.codigo_ingresado = ""
            else:
                state.led.set_blue()
                dia = True

        if state.is_unlocked():
            # Estado abierto.
            state.led.set_green()

            if time.time() - state.ultimo_ingreso_tiempo > KEY_INPUT_TIME_LIMIT and state.ultimo_ingreso_tiempo != 0:
                if state.codigo_ingresado != "":
                    print("Tiempo excedido. Borrando código ingresado.")
                    state.led.set_off()
                    await asyncio.sleep(0.2)
                    state.codigo_ingresado = ""
        await asyncio.sleep(0.01)


def get_app_data() -> dict:
    """Retorna la información que será enviada al maestro."""
    return {"hola": "10"}


async def main():
    await asyncio.gather(
        operations(),                               # Código específico a cada grupo
        micro_monitoring.monitoring(get_app_data)   # Monitoreo con el maestro
    )

asyncio.run(main())
