from machine import Pin, ADC, 
import time
import rp2
from rp2 import PIO
from time import sleep

# Pines
sensor_pin = ADC(Pin(26))  
led_rojo = Pin(16, Pin.OUT)  
led_verde = Pin(17, Pin.OUT) 
led_azul = Pin(18, Pin.OUT)

umbral_luz = 40000 
codigo_correcto = ""
codigo_ingresado = ""
dia = True
candado = True
ultimo_ingreso_tiempo = 0
tiempo_limite = 10
boot_mode = True 

# Variables para control de intentos fallidos y alarma
intentos_fallidos = 0
ultimo_intento_fallido = [0, 0, 0]

alarma_activada = False
inicio_alarma = 0
duracion_alarma = 10  

# Función para manejar la entrada de teclas
def oninput(machine):
    global codigo_correcto
    global codigo_ingresado
    global dia
    global candado
    global led_azul
    global led_rojo
    global led_verde
    global ultimo_ingreso_tiempo
    global tiempo_limite
    global intentos_fallidos, ultimo_intento_fallido, alarma_activada, inicio_alarma, boot_mode

    if alarma_activada:
        print("Alarma activada. No se permiten nuevos intentos.")
        return

    keys = machine.get()
    while machine.rx_fifo():
        keys = machine.get()
    
    pressed = []
    for i in range(len(key_names)):
        if (keys & (1 << i)):
            pressed.append(key_names[i])
            
    
    if not dia:
        print("El LED está en rojo, ignorando entrada de teclas.")
    else:
        if len(pressed) > 0:
            if (pressed[0] == "#") and (candado == True):
                print("Se reinicio el codigo ingresado", candado)
                codigo_ingresado = ""
                return
        if boot_mode :
            if len(pressed) > 0:
                codigo_ingresado += pressed[0]  
                led_rojo.off()
                led_verde.off()
                led_azul.off() 
                sleep(0.2)  
                print("Clave (4 digitos):", codigo_ingresado)     
                if len(codigo_ingresado) == 4:
                    codigo_correcto = codigo_ingresado
                    codigo_ingresado = ""
                    boot_mode = False
                    print("El codigo clave sera: ", codigo_correcto)
                    led_rojo.off()
                    led_verde.off()
                    led_azul.off() 
        else:
            if candado:
                if not dia:
                    print("Boop.")
                else:
                    if len(pressed) > 0:
                        if (pressed[0] == "#"):
                            print("Se reinicio el codigo ingresado")
                            codigo_ingresado = ""
                            return
                        
                        codigo_ingresado += pressed[0]
                        ultimo_ingreso_tiempo = time.time()
                        print("Código ingresado hasta ahora:", codigo_ingresado)
                        led_azul.off()
                        led_rojo.off()
                        led_verde.off()
                        sleep(0.2)
                     
                        # Control de codigo correcto
                        if len(codigo_ingresado) == 4:
                            if codigo_ingresado == codigo_correcto:
                                print("Código correcto. Cambiando a verde.")
                                candado = not candado
                                intentos_fallidos = 0
                            else:
                                print("Código incorrecto. Reiniciando.")                           
                                intentos_fallidos += 1
                                led_rojo.on()
                                sleep(0.4) 
                                ultimo_intento_fallido[intentos_fallidos-1] = time.time()
                            
                                if intentos_fallidos == 3:
                                    if time.time() - ultimo_intento_fallido[0] <= 20:
                                        activar_alarma()
                                    else:
                                        ultimo_intento_fallido[0] = ultimo_intento_fallido[1]
                                        ultimo_intento_fallido[1] = ultimo_intento_fallido[2]
                                        intentos_fallidos = 2
                            codigo_ingresado = ""                  
            else:
                if len(pressed) > 0:
                    codigo_ingresado += pressed[0]
                    if (codigo_ingresado[-1] == "*"):
                        print("Caja cerrada.")
                        candado = not candado
                        codigo_ingresado = ""
                    if (codigo_ingresado == "###"):
                        boot_mode = True
                        candado = True
                        dia = True
                        print("Ingrese la nueva clave.")
                        codigo_ingresado = ""
                             
def activar_alarma():
    global alarma_activada, inicio_alarma
    print("¡ALERTA! Demasiados intentos fallidos. Activando alarma.")
    alarma_activada = True
    inicio_alarma = time.time()

@rp2.asm_pio(set_init=[PIO.IN_HIGH]*4)
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

for i in range(10, 14):
    Pin(i, Pin.IN, Pin.PULL_DOWN)

key_names = "*7410852#963DCBA"
sm = rp2.StateMachine(0, keypad, freq=2000, in_base=Pin(10, Pin.IN, Pin.PULL_DOWN), set_base=Pin(6))
sm.active(1)
sm.irq(oninput)
print("Inicio de la caja fuerte, ingrese una clave para guardarla.")

while True:
    valor_luz = sensor_pin.read_u16()
    if alarma_activada:
        if (time.time() - inicio_alarma) >= duracion_alarma:
            print("Tiempo de alarma terminado. Desactivando alarma.")
            alarma_activada = False
            codigo_ingresado = ""
            intentos_fallidos = 0
        else:
            led_rojo.on()
            led_azul.off()
            sleep(0.2)
            led_rojo.off()
            led_azul.on()
            sleep(0.2)
    else:
        if boot_mode:
            led_rojo.on()
            led_verde.on()
            led_azul.on()
        else:
            if candado:
                if valor_luz > umbral_luz:
                    led_rojo.on()
                    led_verde.off()
                    led_azul.off()
                    dia = False
                    codigo_ingresado = ""
                else:
                    led_rojo.off()
                    led_verde.off()
                    led_azul.on()
                    dia = True
            else:
                led_rojo.off()
                led_verde.on()
                led_azul.off()
                
            if (time.time() - ultimo_ingreso_tiempo > tiempo_limite) and (ultimo_ingreso_tiempo != 0) :
                if codigo_ingresado != "":
                    print("Tiempo excedido. Borrando código ingresado...")
                    led_azul.off()
                    sleep(0.2)
                    codigo_ingresado = ""
    time.sleep(0.01)