import asyncio
import logging
import struct
import time
from datetime import datetime, timedelta
from functools import wraps

import nest_asyncio
from bleak import BleakClient, BleakScanner, BLEDevice, AdvertisementData, BleakGATTCharacteristic

from lywd03mmc.models import SensorData, History, DeviceNotFound

_LOGGER = logging.getLogger(__name__)

_UUID_UNITS = 'EBE0CCBE-7A0A-4B0C-8A1A-6FF2997DA3A6'  # 0x00 - F, 0x01 - C    READ WRITE
_UUID_HISTORY = 'EBE0CCBC-7A0A-4B0C-8A1A-6FF2997DA3A6'  # Last idx 152          READ NOTIFY
_UUID_TIME = 'EBE0CCB7-7A0A-4B0C-8A1A-6FF2997DA3A6'  # 5 or 4 bytes          READ WRITE
_UUID_DATA = 'EBE0CCC1-7A0A-4B0C-8A1A-6FF2997DA3A6'  # 3 bytes               READ NOTIFY
_UUID_BATTERY = 'EBE0CCC4-7A0A-4B0C-8A1A-6FF2997DA3A6'  # 1 byte                READ
_UUID_NUM_RECORDS = 'EBE0CCB9-7A0A-4B0C-8A1A-6FF2997DA3A6'  # 8 bytes               READ
_UUID_RECORD_IDX = 'EBE0CCBA-7A0A-4B0C-8A1A-6FF2997DA3A6'  # 4 bytes               READ WRITE

nest_asyncio.apply()


def _async_to_sync(async_func):
    @wraps(async_func)
    def wrapper(*args, **kwargs):
        async def runner():
            result = await async_func(*args, **kwargs)

            if result is None:
                raise TypeError(f"{async_func.__name__} did not return an awaitable object")

            return result

        return asyncio.run(runner())

    return wrapper


class Lywsd03Scanner:
    devices: {str: BLEDevice}

    async def scan(self):
        def callback(device: BLEDevice, data: AdvertisementData):
            if device.name == 'LYWSD03MMC':
                self._devices[device.address] = device

        scanner = BleakScanner(detection_callback=callback)
        await scanner.start()
        await asyncio.sleep(10)
        await scanner.stop()


class Lywsd03Client:
    UNITS_CODES = {
        b'\x01': '°F',
        b'\x00': '°C',
    }
    UNITS_BYTES = {
        'C': b'\x00',
        'F': b'\x01',
    }

    def __init__(self, mac, notification_timeout=10.0, connection_retry=5):
        self._mac: str = mac
        self._notification_timeout = notification_timeout
        self._connection_retry = connection_retry
        self._handles = {}
        self._tz_offset = None
        self._device_time: datetime = datetime.now()
        self._data = SensorData(0, 0, 0)
        self._history_data: History = History()
        self._history_index = None
        self._context_depth = 0
        self._client: BleakClient = BleakClient(address_or_ble_device=self._mac, timeout=20)
        self._devices = []
        self._connected = False
        self._stored_entries: tuple = ()
        self._latest_record = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        @_async_to_sync
        async def disconnect():
            await self._client.disconnect()
            self._connected = False
            return self._connected

        disconnect()

    @property
    def connected(self):
        return self._connected

    def connect(self):
        @_async_to_sync
        async def _connect():
            retry = 1
            while not self._connected and retry <= self._connection_retry:
                try:
                    print(f'Connecting to {self._mac}, attempt {retry}')
                    if not self._client or not self._client.is_connected:
                        self._client = BleakClient(address_or_ble_device=self._mac, timeout=20)
                    self._connected = await self._client.connect()
                    print(f'Connected to {self._mac}')
                    return True
                except Exception:
                    retry += 1
            return False

        if not _connect():
            raise DeviceNotFound()

    @property
    def temperature(self):
        return self.data.temperature

    @property
    def humidity(self):
        return self.data.humidity

    @property
    def data(self):
        @_async_to_sync
        async def _get_sensor_data():
            self._process_sensor_data(None, await self._client.read_gatt_char(_UUID_DATA))
            return self._data

        return _get_sensor_data()

    @property
    def units(self):
        @_async_to_sync
        async def _units():
            value = await self._client.read_gatt_char(_UUID_UNITS)
            return self.UNITS_CODES[bytes(value)]

        return _units()

    @units.setter
    def units(self, value):

        @_async_to_sync
        async def units_as():
            if value.upper() not in self.UNITS_BYTES.keys():
                raise ValueError('Units value must be one of %s' % self.UNITS_BYTES.keys())

            await self._client.write_gatt_char(_UUID_UNITS, self.UNITS_BYTES[value.upper()])
            return value

        units_as()

    @property
    def battery(self):
        @_async_to_sync
        async def _battery_async():
            return ord(await self._client.read_gatt_char(_UUID_BATTERY))

        return _battery_async()

    @property
    def time(self):
        @_async_to_sync
        async def fn():
            value = await self._client.read_gatt_char(_UUID_TIME)
            if len(value) == 5:
                ts, self.tz_offset = struct.unpack('Ib', value)
            else:
                ts = struct.unpack('I', value)[0]
                self.tz_offset = 0
            self._device_time = datetime.fromtimestamp(ts)
            return self._device_time

        return self._device_time if self._device_time else fn()

    @time.setter
    def time(self, dt: datetime):
        @_async_to_sync
        async def fn():
            data = struct.pack('Ib', int(dt.timestamp()), self.tz_offset)
            await self._client.write_gatt_char(_UUID_TIME, data)
            return dt

        fn()

    @property
    def tz_offset(self):
        if self._tz_offset is not None:
            return self._tz_offset
        elif time.daylight:
            return -time.altzone // 3600
        else:
            return -time.timezone // 3600

    @tz_offset.setter
    def tz_offset(self, tz_offset: int):
        self._tz_offset = tz_offset

    @property
    def history_index(self):
        @_async_to_sync
        async def _history_index_async():
            value = await self._client.read_gatt_char(_UUID_RECORD_IDX)
            _idx = 0 if len(value) == 0 else struct.unpack_from('I', value)
            return _idx

        return _history_index_async()

    @history_index.setter
    def history_index(self, value):

        @_async_to_sync
        async def hist_idx():
            data = struct.pack('I', value)
            await self._client.write_gatt_char(_UUID_RECORD_IDX, data)
            return data

        hist_idx()

    @property
    def stored_entries(self):
        @_async_to_sync
        async def _num_stored_entries():
            value = await self._client.read_gatt_char(_UUID_NUM_RECORDS)

            self._stored_entries = struct.unpack_from('II', value)
            return self._stored_entries

        return self._stored_entries if self._stored_entries else _num_stored_entries()

    @property
    def history_data(self):

        @_async_to_sync
        async def _get_history_data():
            await self._client.start_notify(_UUID_HISTORY, self._process_history_data)

            end_date = self._device_time - timedelta(hours=1)
            while not self._latest_record or self._latest_record <= end_date:
                await asyncio.sleep(1)
            await self._client.stop_notify(_UUID_HISTORY)
            return True

        _get_history_data()
        return self._history_data

    def history(self, time_range: TimeRange = TimeRange.DAY) -> History:
        self.history_index = self.stored_entries[0] - time_range.value
        if self.stored_entries[1] == 0:
            return History()
        return self.history_data

    def _process_sensor_data(self, _, data: bytearray):
        temperature, humidity, voltage = struct.unpack_from('<hBh', data)
        temperature /= 100
        voltage /= 1000

        # Estimate the battery percentage remaining
        battery = min(int(round((voltage - 2.1), 2) * 100), 100)  # 3.1 or above --> 100% 2.1 --> 0 %
        self._data = SensorData(temperature=temperature, humidity=humidity, battery=battery)

    def _process_history_data(self, sender: BleakGATTCharacteristic, data: bytearray):
        (idx, _, max_temp, max_hum, min_temp, min_hum) = struct.unpack_from('<IIhBhB', data)

        # Work out the time of this record by adding the record time to time the device was started
        ts = self.time - timedelta(hours=self.stored_entries[0] - idx, minutes=self.time.minute, seconds=self.time.second, microseconds=self.time.microsecond)

        min_temp /= 10
        max_temp /= 10

        self._latest_record = ts
        self._history_data.add(ts, HistoryRecord(ts, min_temp, max_temp, min_hum, max_hum))
