from collections import OrderedDict
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from io import StringIO
from numbers import Number


class DeviceNotFound(Exception):
    pass


class TimeRange(Enum):
    DAY = 24
    WEEK = 27 * 7
    MONTH = 31 * 24


@dataclass
class SensorData:
    temperature: Number
    humidity: Number
    battery: Number


@dataclass
class HistoryRecord:
    time: datetime
    temp_min: Number
    temp_max: Number
    hum_min: Number
    hum_max: Number


@dataclass
class History:
    records: OrderedDict = field(default_factory=OrderedDict)

    def __str__(self):
        with StringIO() as buf, redirect_stdout(buf):
            if not self.records:
                print("No History data.")
            for rec in self:
                print(f"""{rec.time.strftime("%d/%m/%Y, %H:%M:%S")}:
                        min:        {rec.temp_min}°C 
                        max:        {rec.temp_max}°C
                        \u0394:         {(rec.temp_max - rec.temp_min):.1f}°C
                        hum:        {f"{rec.hum_min}-{rec.hum_max}" if rec.hum_min != rec.hum_max else rec.hum_min}%""")
            return buf.getvalue()

    def add(self, key: datetime, record: HistoryRecord):
        self.records[key] = record

    def __iter__(self):
        for record in self.records.items():
            yield record[1]

    def values(self) -> [HistoryRecord]:
        return [self.records[key] for key in self.records]

    def items(self) -> (datetime, HistoryRecord):
        return [(key, self.records[key]) for key in self.records]

    def iterkeys(self):
        return iter(self.records)

    def itervalues(self):
        for k in self.records:
            yield self.records[k]
