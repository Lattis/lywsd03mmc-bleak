#!/usr/bin/env python

from lywd03mmc import Lywsd03Client, TimeRange, History

macs = {
    'Kancl': 'A03985EF-A478-E6BB-02DF-3EC0858D5361',
    'Viki': '93EB2DC5-1CD7-1C07-CDC7-3F09A1C4666D',
    '0': '6647CF9F-B5F2-091B-6816-228D9C410825',
    'spajz': '6DD3DDFA-98DF-8A65-1D4C-04DD9CD7FFF1',
}


def test(add):
    with Lywsd03Client(add) as client:
        if client.connected:
            # print('Synchronizing time of {}'.format(add))
            # client.time = datetime.now()

            client.units = 'C'
            print(f"Units {client.units}")
            print(client.time.strftime("%d/%m/%Y, %H:%M:%S"))
            print(f'Battery:         {client.battery}')

            data = client.data
            print(f'Temperature:     {data.temperature}°C')
            print(f'Humidity:        {data.humidity}%')

            read_history(client, )


def read_history(client, time_range=TimeRange.DAY):
    history: History = client.history(time_range=time_range)
    print(history)


if __name__ == '__main__':
    [test(mac) for mac in macs.values()]

    # history: History = History()
    # now = datetime.now()
    # history.add(now, HistoryRecord(now, 1, 2, 3, 4))
    # history.add(now - timedelta(hours=1), HistoryRecord(now - timedelta(hours=1), 1, 2, 3, 4))
    # history.add(now - timedelta(hours=2), HistoryRecord(now - timedelta(hours=2), 1, 2, 3, 4))
    # history.add(now - timedelta(hours=2), HistoryRecord(now - timedelta(hours=2), 1, 2, 3, 4))
    #
    # print(history)
