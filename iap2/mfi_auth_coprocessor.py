import smbus2
import time
from struct import Struct

Word = Struct(">H")
# use bit-banged i2c, because coprocessor is to slow for native i2c 'dtoverlay=i2c-gpio,i2c_gpio_sda=2,i2c_gpio_scl=3,i2c_gpio_delay_us=50'
bus = smbus2.SMBus("/dev/i2c-11")
DEV_ADDR = 0x10


def _read_i2c(addr, n):
    addr_msg = smbus2.i2c_msg.write(DEV_ADDR, bytes([addr]))
    read_msg = smbus2.i2c_msg.read(DEV_ADDR, n)
    for _ in range(5):
        try:
            bus.i2c_rdwr(addr_msg, read_msg)
            return bytes(read_msg)
        except OSError:
            time.sleep(0.0005)
    raise Exception("timeout")


def _write_i2c(addr, arr):
    bus.write_i2c_block_data(DEV_ADDR, addr, [int(x) for x in arr])


def read_certificate():
    print(bus.read_word_data(DEV_ADDR, 0x30))
    size = Word.unpack(_read_i2c(0x30, 2))[0]  # Read Accessory Certificate Data Length
    return _read_i2c(0x31, size)  # Read Accessory Certificate Data


def generate_challenge_response(challenge):
    _write_i2c(0x20, Word.pack(len(challenge)))  # Write Challenge Data Length
    _write_i2c(0x21, challenge)  # Write Challenge Data
    bus.write_byte_data(DEV_ADDR, 0x10, 0x01)  # Write Authentication Control and Status = Start
    time.sleep(0.01)
    for _ in range(10):
        try:
            if bus.read_byte_data(DEV_ADDR, 0x10) == 0x10:  # Read Authentication Control and Status == Success
                break
        except OSError:
            pass
        time.sleep(0.1)
    else:
        raise Exception("timeout")
    size = Word.unpack(_read_i2c(0x11, 2))[0]  # Read Challenge Response Data Length
    return _read_i2c(0x12, size)  # Read Challenge Response Data


if __name__ == "__main__":
    print("CERT", read_certificate().hex())
    print("CERT", generate_challenge_response(b"12211213131231231231").hex())
