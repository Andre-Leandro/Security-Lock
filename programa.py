from machine import Pin, ADC
import time
import rp2
from rp2 import PIO
from machine import Pin
from time import sleep

# Pines
sensor_pin = ADC(Pin(26))  
led_rojo = Pin(16, Pin.OUT)  
led_verde = Pin(17, Pin.OUT) 
led_azul = Pin(18, Pin.OUT)  

umbral_luz = 40000  

# Código predefinido para comparar
codigo_correcto = ""
codigo_ingresado = ""
dia = True
candado = False



# Función para manejar la entrada de teclas
def oninput(machine):
    global codigo_correcto
    global codigo_ingresado
    global dia
    global candado
    global led_azul
    global led_rojo
    global led_verde
    keys = machine.get()
    while machine.rx_fifo():
        keys = machine.get()
    
    pressed = []
    for i in range(len(key_names)):
        if (keys & (1 << i)):
            pressed.append(key_names[i])

    ##--------------Condicion para configurar el codigo del candado
    if len(codigo_correcto)<4 :
        if len(pressed) > 0:
            codigo_correcto += pressed[0]  
            print("Ingresar clave (4 digitos):", codigo_correcto)
                
            if len(codigo_correcto) == 4:
                print("El codigo clave sera: ", codigo_correcto)
    #---------------Fin de la condicion

    else:
        if dia:
            print("El LED está en rojo, ignorando entrada de teclas.")

        else:
            if len(pressed) > 0:
                codigo_ingresado += pressed[0]  
                print("Código ingresado hasta ahora:", codigo_ingresado)
                led_azul.off()
                led_rojo.off()
                led_verde.off()
                
                
                if len(codigo_ingresado) == 4:
                    if codigo_ingresado == codigo_correcto:
                        print("Código correcto. Cambiando a verde.")
                        candado = not candado
                    else:
                        print("Código incorrecto. Reiniciando.")
                    codigo_ingresado = ""  


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

print("Por favor, ingrese un código en el teclado numérico, o presione Ctrl+C para ingresar al REPL.")

# Bucle principal
while True:
    valor_luz = sensor_pin.read_u16()
    # print(valor_luz)
    #print(valor_luz)


    if not candado:
      if valor_luz > umbral_luz:
 
          led_rojo.on()
          led_verde.off()
          led_azul.off()  
          dia = True
      else:
          led_rojo.off()
          led_verde.off()
          led_azul.on()
          dia = False
    else:
      led_rojo.off()
      led_verde.on()
      led_azul.off()
    time.sleep(0.1)
