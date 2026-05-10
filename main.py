
import spidev
import time
import RPi.GPIO as GPIO

# --- Configuración de Pines (Referencia para Víctor) ---
# VCC: 3.3V (Pin 1 RPi) | GND: GND (Pin 6 RPi)
# CS: CE0 (GPIO 8)      | SCLK: SCLK (GPIO 11)
# DIN: MOSI (GPIO 10)   | DOUT: MISO (GPIO 9)

# Definición de Comandos ADS1262/1263
RESET = 0x06
START = 0x08
STOP  = 0x0A
RDATA = 0x12
RREG  = 0x20  
WREG  = 0x40  

class ADS126x:
    def __init__(self, bus=0, device=0):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 1000000 
        self.spi.mode = 0b01 
        
    def send_command(self, cmd):
        self.spi.xfer2([cmd])

    def read_reg(self, reg, count=1):
        # Envía comando, espera y lee
        data = self.spi.xfer2([RREG | reg, count - 1] + [0]*count)
        return data[2:]

    def write_reg(self, reg, value):
        self.spi.xfer2([WREG | reg, 0x00, value])

    def read_data(self):
        # Leemos 6 bytes: Status + 4 bytes Data + Checksum
        raw = self.spi.xfer2([RDATA] + [0]*6)
        return raw[1:]

def main():
    adc = None # Inicializamos para que el finally no falle
    try:
        adc = ADS126x()
        print("--- Iniciando sistema del Túnel de Viento ---")
        
        print("Reseteando ADS126x...")
        adc.send_command(RESET)
        time.sleep(0.2)

        # 1. Verificar Identidad
        dev_id = adc.read_reg(0x00)
        print(f"ID del Dispositivo detectado: {hex(dev_id[0]) if dev_id else 'Error'}")

        # 2. Configurar ADC (Gain 1, 20 SPS)
        adc.write_reg(0x02, 0x00) 
        
        print("Iniciando conversión continua...")
        adc.send_command(START)

        while True:
            data_packet = adc.read_data()
            
            # Reconstrucción de los 32 bits (4 bytes de datos)
            # El paquete suele ser: [STATUS, BYTE3, BYTE2, BYTE1, BYTE0, CHECKSUM]
            # Usamos los índices 1 a 4 para los datos.
            val = (data_packet[1] << 24) | (data_packet[2] << 16) | (data_packet[3] << 8) | data_packet[4]
            
            # Manejo de signo (Complemento a 2 para 32 bits)
            if val & (1 << 31):
                val -= (1 << 32)
                
            print(f"Lectura Raw: {val}")
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nPrueba finalizada por el usuario.")
    except Exception as e:
        print(f"\nError inesperado: {e}")
    finally:
        if adc:
            adc.send_command(STOP) # Detenemos el ADC antes de salir
            adc.spi.close()
            print("Conexión SPI cerrada correctamente.")

if __name__ == "__main__":
    main()