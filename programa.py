from machine import Pin, ADC
import time
import rp2
import uasyncio as asyncio
import micro_monitoring

FAILED_ATTEMPTS_LIMIT = 3
"""Cantidad de intentos erróneos que el candado tolera."""
FAILED_ATTEMPTS_INTERVAL_MS = 2 * 60 * 1000
"""En los últimos N milisegundos puede haber hasta `FAILED_ATTEMPTS_TOLERANCE` intentos erróneos."""
ALARM_DURATION_MS = 5 * 60 * 1000
"""Milisegundos que dura el estado de alarma."""
LED_BLINK_DURATION_SECONDS = 0.2
"""Segundos que dura un instante en el que el LED parpadea."""
LED_ALARMED_FLASH_DURATION_SECONDS = 0.5
"""Segundos que dura cada color al alternar entre rojo y azul en el estado alarmado."""

KEYPAD_ROWS = [Pin(i, Pin.OUT) for i in [9, 8, 7, 6]]
"""Pines para leer las 4 filas del keypad."""
KEYPAD_COLUMNS = [Pin(i, Pin.IN, Pin.PULL_DOWN) for i in [10, 11, 12, 13]]
"""Pines para leer las 4 columnas del keypad."""
KEYPAD_KEY_NAMES = [
    ['1', '2', '3', 'A'],
    ['4', '5', '6', 'B'],
    ['7', '8', '9', 'C'],
    ['*', '0', '#', 'D']]
"""Mapa de las teclas del keypad 4x4. Las letras ABCD no se utilizan."""
KEYPAD_INPUT_TIMEOUT_MS = 5000
"""Milisegundos que persiste un input del tablero antes de restablecerse a nulo."""

LDR_SENSOR = ADC(Pin(26))
"""Pin para leer el output del LDR (fotosensor)."""
RPI_VOLTAGE_REFERENCE_VOLTS = 3.3
"""Voltaje (en volts) de referencia de la Raspberry Pi Pico W."""
LIGHT_THRESHOLD_VOLTS = 1.5
"""Valor en volts máximo que indica la mínima iluminación aceptable. A menor iluminación, el LDR deja pasar mayor voltaje."""


class Led():
    """Conjunto de los pines rojo, verde y azul del foco LED."""

    def __init__(self):
        """Inicializa los pines para cada color."""
        self.red = Pin(16, Pin.OUT)
        self.green = Pin(17, Pin.OUT)
        self.blue = Pin(18, Pin.OUT)

    def set_values(self, red: int, green: int, blue: int):
        """Enciende los colores con valor 1 o mayor. Si un parámetro es 0, lo apaga."""
        self.red.value(red)
        self.green.value(green)
        self.blue.value(blue)

    def set_off(self):
        """Apaga todos los tres colores del foco LED."""
        self.set_values(0, 0, 0)

    def set_white(self):
        """Pone el LED de color blanco."""
        self.set_values(1, 1, 1)

    def set_red(self):
        """Pone el LED de color rojo."""
        self.set_values(1, 0, 0)

    def set_blue(self):
        """Pone el LED de color azul."""
        self.set_values(0, 0, 1)

    def set_green(self):
        """Pone el LED de color verde."""
        self.set_values(0, 1, 0)

    async def blink(self):
        """Apaga el LED por un pequeño instante."""
        r, g, b = self.red.value(), self.green.value(), self.blue.value()
        self.set_off()
        await asyncio.sleep(LED_BLINK_DURATION_SECONDS)
        self.set_values(r, g, b)


class State:
    """Estados posibles del candado inteligente."""
    DISABLED = "DISABLED"
    BOOT_MODE = "BOOT_MODE"
    LOCKED = "LOCKED"
    OPEN = "OPEN"
    ALARMED = "ALARMED"


class SmartLock:
    """Contiene todos los datos del candado inteligente. Facilita calcular en qué estado se encuentra."""

    def __init__(self):
        # Variables para los inputs del tablero 4x4
        self.last_input_time: int = 0
        self.input: str = ""
        self.password: str = ""

        # Variables para los estados del candado
        self.state: State = State.DISABLED
        self.light_value: int = 0
        self.led: Led = Led()
        self.led.set_off()

        # Variables para la alarma
        self.alarm_start_time: int = 0
        self.failed_attempts: list[int] = []

    def has_daylight(self):
        return self.light_value <= LIGHT_THRESHOLD_VOLTS

    def to_disabled(self):
        """Transicionar al estado deshabilitado."""
        self.state = State.DISABLED
        self.input = ""
        self.led.set_off()

    def to_boot_mode(self):
        """Transicionar al estado inicialización."""
        self.state = State.BOOT_MODE
        self.input = ""
        self.failed_attempts = []
        self.led.set_white()

    def to_locked(self):
        """Transicionar al estado cerrado."""
        self.state = State.LOCKED
        self.input = ""
        self.failed_attempts = []
        self.led.set_blue()

    def to_open(self):
        """Transicionar al estado abierto."""
        self.state = State.OPEN
        self.input = ""
        self.failed_attempts = []
        self.led.set_green()

    def to_alarmed(self):
        """Transicionar al estado alarmado."""
        self.state = State.ALARMED
        self.input = ""
        self.failed_attempts = []
        self.alarm_start_time = time.ticks_ms()
        print("¡ALERTA! Demasiados intentos fallidos. Alarma activada.")

    async def handle_failed_attempt(self):
        """Procesar un intento fallido de desbloquear el candado cerrado. Dispara la alarma si 
        alcanza los `FAILED_ATTEMPTS_TOLERANCE` en un tiempo `FAILED_ATTEMPTS_INTERVAL_SECONDS`."""
        self.led.set_red()
        await asyncio.sleep(LED_BLINK_DURATION_SECONDS * 2)
        self.led.set_blue()
        self.input = ""

        attempt_time = time.ticks_ms()
        self.failed_attempts.append(attempt_time)

        too_many_attempts = len(self.failed_attempts) >= FAILED_ATTEMPTS_LIMIT
        if too_many_attempts:
            # Calcular el tiempo que hubo entre los últimos intentos fallidos
            oldest_attempt = self.failed_attempts[-FAILED_ATTEMPTS_LIMIT+1]
            if time.ticks_diff(attempt_time, oldest_attempt) < FAILED_ATTEMPTS_INTERVAL_MS:
                # Disparar la alarma si hubo muchos intentos fallidos en poco tiempo
                self.to_alarmed()


# Estado de cada tecla del keypad 4x4. Si es `True`, está siendo presionada
keypad_state = [[False for _ in range(4)] for _ in range(4)]


def read_keypad():
    """Iterar las filas y columnas del tablero 4x4 para devolver una posible tecla presionada."""
    for row_index, row_pin in enumerate(KEYPAD_ROWS):
        # Poner la fila a HIGH
        row_pin.value(1)
        for col_index, col_pin in enumerate(KEYPAD_COLUMNS):
            is_pressed = col_pin.value() == 1
            was_being_pressed = keypad_state[row_index][col_index] == 1
            if is_pressed != was_being_pressed:
                keypad_state[row_index][col_index] = is_pressed

                if is_pressed:
                    # Se está apretando un botón que antes no estaba apretado, entonces es un input
                    # Guardar el tiempo del input para luego calcular timeout por inactividad
                    sl.last_input_time = time.ticks_ms()
                    # Poner la fila de nuevo a LOW
                    row_pin.value(0)
                    return KEYPAD_KEY_NAMES[row_index][col_index]
        # Poner la fila de nuevo a LOW
        row_pin.value(0)
    return None


sl = SmartLock()


async def handle_keypad_input():
    """Manejar la entrada de teclas del tablero 4x4."""
    if sl.state == State.DISABLED or (sl.state == State.BOOT_MODE or sl.state == State.LOCKED) and not sl.has_daylight():
        print("No hay suficiente luz. Ignorando entrada de teclas.")
        sl.to_disabled()
        return

    key = read_keypad()

    if key is None:
        # No hay inputs para procesar
        return

    if sl.state == State.ALARMED:
        print("Alarma activada. No se permiten nuevos intentos.")
        return

    # Parpadeo del LED para dar feedback de la recepción del input
    await sl.led.blink()

    if sl.state == State.OPEN:
        if key == "*":
            # Cerrar caja y pasar al estado cerrado
            print("Cerrando caja.")
            sl.to_locked()
        if key == "#":
            sl.input += key
            if sl.input.endswith("###"):
                # Reestablecer clave, pasar al estado inicialización
                print("Restableciendo clave.")
                sl.to_boot_mode()
        return

    if key == "#":
        # Reestablecer el input
        print("Input reestablecido a nulo.")
        sl.input = ""
        return

    if key == "*":
        # Ignorar teclas que no son dígitos
        print("Input '*' ignorado.")
        return

    sl.input += key

    if sl.state == State.BOOT_MODE:
        print("Clave:", sl.input)
        if len(sl.input) == 4:
            # PIN de seguridad establecido, pasar al estado cerrado
            sl.password = sl.input
            print("Código establecido: ", sl.password)
            sl.to_locked()
            return

    if sl.state == State.LOCKED:
        if len(sl.input) == 4:
            if sl.input == sl.password:
                # PIN correcto, pasar al estado abierto
                print("Código correcto. Pasando a estado abierto.")
                sl.to_open()
            else:
                # PIN incorrecto, agregar un intento fallido
                print("Código incorrecto. Reiniciando input.")
                await sl.handle_failed_attempt()


def get_illumination_voltage():
    """Devuelve el voltaje que el fotosensor LDR deja pasar. A mayor iluminación, menor voltaje."""
    voltage = LDR_SENSOR.read_u16() / 65535 * RPI_VOLTAGE_REFERENCE_VOLTS
    return voltage


async def operations():
    """Funcionamiento del candado inteligente."""


async def operations():
    """En cada tick, leer la entrada del keypad 4x4 y actualizar el estado del candado.
    Luego, producir la salida del LED RGB en base al estado del candado y la iluminación del sensor LDR."""
    print("Caja fuerte iniciada. Registre su clave: ")

    while True:
        await handle_keypad_input()

        # Actualizar el valor del sensor de iluminación
        sl.light_value = get_illumination_voltage()
        if (sl.state == State.BOOT_MODE or sl.state == State.LOCKED) and not sl.has_daylight():
            # Si no hay suficiente luz en estado cerrado o inicialización, pasar al estado deshabilitado
            sl.to_disabled()
            continue

        if sl.state == State.DISABLED and sl.has_daylight():
            # Volvió la luz, salir del estado deshabilitado
            if sl.password == "":
                sl.to_boot_mode()
            else:
                sl.to_locked()

        if sl.state == State.ALARMED:
            duration = time.ticks_diff(time.ticks_ms(), sl.alarm_start_time)
            if duration >= ALARM_DURATION_MS:
                # Finalizar el estado alarmado
                sl.to_locked()
                print("Tiempo de alarma terminado. Alarma desactivada.")
            else:
                sl.led.set_red()
                await asyncio.sleep(LED_ALARMED_FLASH_DURATION_SECONDS)
                sl.led.set_blue()
                await asyncio.sleep(LED_ALARMED_FLASH_DURATION_SECONDS)

        input_inactivity = time.ticks_diff(time.ticks_ms(), sl.last_input_time)
        if input_inactivity > KEYPAD_INPUT_TIMEOUT_MS:
            # Timeout por inactividad
            if sl.input != "":
                print("Tiempo excedido. Borrando código ingresado.")
                sl.input = ""
                await sl.led.blink()

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
