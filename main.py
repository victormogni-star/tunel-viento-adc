import spidev
import time
import RPi.GPIO as GPIO
from kyaserv_cz100_mapper import KyaservCZ100Mapper

# --- Configuración de Pines ---
# VCC: 3.3V (Pin 1)  | GND: GND (Pin 6)
# CS: CE0 (GPIO 8)   | SCLK: SCLK (GPIO 11)
# DIN: MOSI (GPIO 10)| DOUT: MISO (GPIO 9)

# Comandos ADS1256
RESET = 0xFE
RDATAC= 0x03   # Read Data Continuously
SDATAC= 0x0F   # Stop Read Data Continuously
RDATA = 0x01   # Read Data (single shot)
RREG  = 0x10
WREG  = 0x50
SYNC  = 0xFC
WAKEUP= 0x00


class ADS1256:
    def __init__(self, bus=0, device=0):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 1_000_000
        self.spi.mode = 0b01

    def send_command(self, cmd):
        self.spi.xfer2([cmd])

    def read_reg(self, reg, count=1):
        data = self.spi.xfer2([RREG | reg, count - 1] + [0] * count)
        return data[2:]

    def write_reg(self, reg, value):
        self.spi.xfer2([WREG | reg, 0x00, value])

    def read_data(self) -> int:
        """
        Lee una conversión del ADS1256.
        Retorna entero con signo (complemento a 2, 24 bits).
        """
        # ADS1256: RDATA + 3 bytes de datos (24 bits, sin status ni checksum)
        raw = self.spi.xfer2([RDATA, 0x00, 0x00, 0x00])
        val = (raw[1] << 16) | (raw[2] << 8) | raw[3]

        # Complemento a 2 para 24 bits
        if val & (1 << 23):
            val -= (1 << 24)

        return val


def main():
    adc    = None
    mapper = KyaservCZ100Mapper()

    try:
        adc = ADS1256()
        print("--- Iniciando sistema del Túnel de Viento ---")

        print("Reseteando ADS1256...")
        adc.send_command(RESET)
        time.sleep(0.2)

        # Verificar identidad (registro 0x00, bits [4:0] = 0x03 para ADS1256)
        dev_id = adc.read_reg(0x00)
        print(f"ID del dispositivo: {hex(dev_id[0]) if dev_id else 'Error'}")

        # Configurar PGA=64 (bits [2:0] = 0b110) y MUX diferencial AIN0/AIN1
        adc.write_reg(0x00, 0x01)   # MUX: AIN0+ / AIN1-
        adc.write_reg(0x02, 0x06)   # ADCON: PGA = 64  ← crítico para la celda

        # Tara: con túnel apagado y sin carga
        print("Tomando tara... (asegurate de que no haya carga)")
        time.sleep(0.5)
        adc.send_command(SYNC)
        adc.send_command(WAKEUP)
        mapper.set_tara(adc.read_data())

        print("Iniciando lectura continua. Ctrl+C para detener.")
        adc.send_command(RDATAC)

        while True:
            val = adc.read_data()
            r   = mapper.read_kg(val)

            estado = "OK" if r["valid"] else "OVERRANGE"
            print(
                f"Raw: {val:>10}  |  "
                f"{r['kg']:>7.3f} kg  |  "
                f"{r['voltaje_mv']:>6.3f} mV  |  {estado}"
            )
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nPrueba finalizada por el usuario.")
    except Exception as e:
        print(f"\nError inesperado: {e}")
    finally:
        if adc:
            adc.send_command(SDATAC)
            adc.spi.close()
            print("Conexión SPI cerrada correctamente.")


if __name__ == "__main__":
    main()
