from machine import Pin, ADC
import time
import rp2
import uasyncio as asyncio
import micro_monitoring

FAILED_ATTEMPTS_LIMIT = 3
"""Cantidad de intentos erróneos que el candado tolera."""
FAILED_ATTEMPTS_INTERVAL_MS = 5000
"""En los últimos N milisegundos puede haber hasta `FAILED_ATTEMPTS_TOLERANCE` intentos erróneos."""
ALARM_DURATION_MS = 10000
"""Milisegundos que dura el estado de alarma."""
LED_BLINK_DURATION_SECONDS = 0.2
"""Segundos que dura un instante en el que el LED parpadea."""
LED_ALARMED_FLASH_DURATION_SECONDS = 0.5
"""Segundos que dura cada color al alternar entre rojo y azul en el estado alarmado."""

KEYPAD_KEY_NAMES = "*7410852#963DCBA"
"""Teclas del tablero 4x4. Van de abajo a arriba, de izqquierda a derecha."""
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

    def blink(self):
        """Apaga el LED por un pequeño instante."""
        r, g, b = self.red.value(), self.green.value(), self.blue.value()
        self.set_off()
        time.sleep(LED_BLINK_DURATION_SECONDS)
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

    def handle_failed_attempt(self):
        """Procesar un intento fallido de desbloquear el candado cerrado. Dispara la alarma si 
        alcanza los `FAILED_ATTEMPTS_TOLERANCE` en un tiempo `FAILED_ATTEMPTS_INTERVAL_SECONDS`."""
        self.led.set_red()
        time.sleep(LED_BLINK_DURATION_SECONDS * 2)
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

# Rutina ensamblada PIO para manejar el teclado matricial


@rp2.asm_pio(set_init=[rp2.PIO.IN_HIGH]*4)
def keypad():
    wrap_target()       # Inicio del ciclo principal
    set(y, 0)           # Inicializa el registro Y a 0
    label("1")          # Etiqueta de reinicio del ciclo
    mov(isr, null)      # Limpia el registro ISR
    set(pindirs, 1)     # Activa la primera fila del teclado
    in_(pins, 4)        # Lee 4 pines de entrada (columnas)
    set(pindirs, 2)     # Activa la segunda fila del teclado
    in_(pins, 4)        # Lee 4 pines de entrada (columnas)
    set(pindirs, 4)     # Activa la tercera fila del teclado
    in_(pins, 4)        # Lee 4 pines de entrada (columnas)
    set(pindirs, 8)     # Activa la cuarta fila del teclado
    in_(pins, 4)        # Lee 4 pines de entrada (columnas)
    mov(x, isr)         # Mueve el contenido del ISR a X
    jmp(x_not_y, "13")  # Salta a "13" si X es diferente de Y
    jmp("1")            # Vuelve a "1" si no hay cambios
    label("13")         # Etiqueta que indica un cambio detectado
    push(block)         # Empuja el contenido del ISR en la pila
    irq(0)              # Genera una interrupción IRQ 0
    mov(y, x)           # Actualiza Y con el valor de X
    jmp("1")            # Vuelve a "1" para seguir escaneando
    wrap()              # Fin del ciclo principal


sl = SmartLock()


def get_pressed_key(machine) -> str:
    """Obtiene las teclas ingresadas del tablero 4x4."""
    keys = machine.get()
    while machine.rx_fifo():
        keys = machine.get()

    pressed = []
    for i in range(len(KEYPAD_KEY_NAMES)):
        if (keys & (1 << i)):
            pressed.append(KEYPAD_KEY_NAMES[i])

    # Guardar el tiempo de este input para luego calcular el timeout por inactividad
    if len(pressed) > 0:
        sl.last_input_time = time.ticks_ms()
        return pressed[0]
    else:
        return ""


def oninput(machine):
    """Manejar la entrada de teclas del tablero 4x4."""
    if sl.state == State.DISABLED or (sl.state == State.BOOT_MODE or sl.state == State.LOCKED) and not sl.has_daylight():
        print("No hay suficiente luz. Ignorando entrada de teclas.")
        sl.to_disabled()
        return

    key = get_pressed_key(machine)

    if key == "":
        # No hay inputs para procesar
        return

    if sl.state == State.ALARMED:
        print("Alarma activada. No se permiten nuevos intentos.")
        return

    # Parpadeo del LED para dar feedback de la recepción del input
    sl.led.blink()
    sl.input += key

    if sl.state == State.OPEN:
        if key == "*":
            # Cerrar caja y pasar al estado cerrado
            print("Cerrando caja.")
            sl.to_locked()
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
                sl.handle_failed_attempt()
        return


def get_illumination_voltage():
    """Devuelve el voltaje que el fotosensor LDR deja pasar. A mayor iluminación, menor voltaje."""
    voltage = LDR_SENSOR.read_u16() / 65535 * RPI_VOLTAGE_REFERENCE_VOLTS
    return voltage


async def operations():
    """Funcionamiento del candado inteligente."""

    # Instanciar pines
    for i in range(10, 14):
        Pin(i, Pin.IN, Pin.PULL_DOWN)

    state_machine = rp2.StateMachine(0, keypad, freq=2000, in_base=Pin(
        10, Pin.IN, Pin.PULL_DOWN), set_base=Pin(6))
    state_machine.active(1)
    state_machine.irq(oninput)
    print("Caja fuerte iniciada. Registre su clave: ")

    while True:
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
                sl.led.blink()

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
