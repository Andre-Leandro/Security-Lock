from machine import Pin, ADC
import time
import rp2
import uasyncio as asyncio
import micro_monitoring

FAILED_ATTEMPTS_TOLERANCE = 3
"""Cantidad de intentos erróneos que el candado tolera."""
FAILED_ATTEMPTS_INTERVAL_SECONDS = 20
"""Los últimos N segundos en los que puede haber hasta `FAILED_ATTEMPTS_TOLERANCE` intentos erróneos."""
LED_BLINK_DURATION_SECONDS = 0.2
"""Segundos que dura un instante en el que el LED parpadea."""
ALARM_DURATION_SECONDS = 10
"""Segundos que dura el estado de alarma."""
KEY_INPUT_TIMEOUT_SECONDS = 10
"""Segundos que persiste un input del tablero antes de restablecerse a nulo."""
LIGHT_THRESHOLD = 40_000
"""Valor digital máximo del sensor de iluminación aceptable."""


class Led():
    """Conjunto de los pines rojo, verde y azul del foco LED."""

    def __init__(self):
        """Inicializa los pines para cada color."""
        self.red = Pin(16, Pin.OUT)
        self.green = Pin(17, Pin.OUT)
        self.blue = Pin(18, Pin.OUT)

    def set_off(self):
        """Apaga todos los tres colores del foco LED."""
        self.red.off(), self.green.off(), self.blue.off()

    def set_values(self, red: int, green: int, blue: int):
        """Enciende los colores con valor 1 o mayor. Si un parámetro es 0, lo apaga."""
        self.red.value(red)
        self.green.value(green)
        self.blue.value(blue)

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


class State():
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
        self.light_value: int = 0
        self.state: State = State.BOOT_MODE
        self.led: Led = Led()
        self.led.set_white()

        # Variables para la alarma
        self.alarm_start_time: int = 0
        self.failed_attempts: list[int] = []

    def has_daylight(self):
        print(self.light_value)
        return self.light_value >= LIGHT_THRESHOLD

    def is_disabled(self):
        return self.state == State.DISABLED

    def is_boot_mode(self):
        return self.state == State.BOOT_MODE

    def is_locked(self):
        return self.state == State.LOCKED

    def is_open(self):
        return self.state == State.OPEN

    def is_alarmed(self):
        return self.state == State.ALARMED

    def to_disabled(self):
        """Transicionar al estado deshabilitado."""
        self.state = State.DISABLED
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
        self.alarm_start_time = time.time()
        print("¡ALERTA! Demasiados intentos fallidos. Alarma activada.")

    def handle_failed_attempt(self):
        """Procesar un intento fallido de desbloquear el candado cerrado. Dispara la alarma si 
        alcanza los `FAILED_ATTEMPTS_TOLERANCE` en un tiempo `FAILED_ATTEMPTS_INTERVAL_SECONDS`."""
        self.led.set_red()
        time.sleep(LED_BLINK_DURATION_SECONDS)
        self.led.set_blue()
        self.input = ""

        attempt_time = time.time()
        self.failed_attempts.append(attempt_time)

        if len(self.failed_attempts) >= FAILED_ATTEMPTS_TOLERANCE:
            # Calcular el tiempo que hubo entre los últimos N intentos fallidos
            time_difference = attempt_time - self.failed_attempts[2]
            if time_difference < FAILED_ATTEMPTS_INTERVAL_SECONDS:
                # Disparar la alarma si hubo muchos intentos fallidos Y en poco tiempo
                self.to_alarmed()


sl = SmartLock()

LIGHT_SENSOR = ADC(Pin(26))
KEY_NAMES = "*7410852#963DCBA"


def get_pressed_keys(machine) -> list[str]:
    """Obtiene las teclas ingresadas del tablero 4x4."""
    keys = machine.get()
    while machine.rx_fifo():
        keys = machine.get()

    pressed = []
    for i in range(len(KEY_NAMES)):
        if (keys & (1 << i)):
            pressed.append(KEY_NAMES[i])

    # Guardar el tiempo de este input para luego calcular el timeout por inactividad
    sl.last_input_time = time.time() if len(pressed) > 0 else 0

    return pressed


def oninput(machine):
    """Manejar la entrada de teclas del tablero 4x4."""
    if (sl.is_boot_mode() or sl.is_locked()) and not sl.has_daylight():
        print("No hay suficiente luz. Ignorando entrada de teclas.")
        sl.to_disabled()
        return

    pressed = get_pressed_keys(machine)

    if len(pressed) == 0:
        # No hay inputs para procesar
        return

    key = pressed[0]

    if sl.is_alarmed():
        print("Alarma activada. No se permiten nuevos intentos.")
        return

    # Parpadeo del LED para dar feedback de la recepción del input
    sl.led.blink()

    if key == "#":
        # Reestablecer el input
        print("Input reestablecido a nulo.")
        sl.input = ""
        return

    if sl.is_open():
        if key == "*":
            # Cerrar caja y pasar al estado cerrado
            print("Cerrando caja.")
            sl.to_locked()
        if sl.input == "###":
            # Reestablecer clave, pasar al estado inicialización
            print("Restableciendo clave.")
            sl.to_boot_mode()
        return

    if key == "*":
        # Ignorar teclas que no son dígitos
        print("* ignorado.")
        return

    if sl.is_boot_mode():
        sl.input += key
        print("Clave:", sl.input)
        if len(sl.input) == 4:
            # PIN de seguridad establecido, pasar al estado cerrado
            sl.password = sl.input
            print("Código establecido: ", sl.password)
            sl.to_locked()
            return

    if sl.is_locked():
        sl.input += key
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
    return LIGHT_SENSOR.read_u16()


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
        # FIXME: valor del sensor de iluminación no es el que debería ser. Ni aunque lo tape con el dedo da valor bajo.
        sl.light_value = get_light_value()
        if not sl.has_daylight() and (sl.is_boot_mode() or sl.is_locked()):
            # Si no hay suficiente luz en estado cerrado o inicialización, pasar al estado deshabilitado
            print("hola")
            sl.to_disabled()

        if sl.is_alarmed():
            if time.time() - sl.alarm_start_time >= ALARM_DURATION_SECONDS:
                # Finalizar el estado alarmado
                sl.to_locked()
                print("Tiempo de alarma terminado. Alarma desactivada.")
            else:
                sl.led.red.on()
                sl.led.blue.off()
                await asyncio.sleep(LED_BLINK_DURATION_SECONDS)
                sl.led.red.off()
                sl.led.blue.on()
                await asyncio.sleep(LED_BLINK_DURATION_SECONDS)

        if sl.last_input_time != 0 and time.time() - sl.last_input_time > KEY_INPUT_TIMEOUT_SECONDS:
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
