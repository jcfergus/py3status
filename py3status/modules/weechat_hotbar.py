# -*- coding: utf-8 -*-
"""
Display air quality polluting in a given location.

An air quality index (AQI) is a number used by government agencies to communicate
to the public how polluted the air currently is or how polluted it is forecast to
become. As the AQI increases, an increasingly large percentage of the population
is likely to experience increasingly severe adverse health effects. Different
countries have their own air quality indices, corresponding to different national
air quality standards.

Configuration parameters:
    auth_token: Personal token required. See https://aqicn.org/data-platform/token
        for more information. (default 'demo')
    cache_timeout: refresh interval for this module. A message from the site:
        The default quota is max 1000 requests per minute (~16RPS) and with
        burst up to 60 requests. See https://aqicn.org/api/ for more information.
        (default 3600)
    format: display format for this module
        (default '[\?color=aqi {city_name}: {aqi} {category}]')
    format_datetime: specify strftime characters to format (default {})
    location: location or uid to query. To search for nearby stations in Kraków,
        try `https://api.waqi.info/search/?token=YOUR_TOKEN&keyword=kraków`
        For best results, use uid instead of name in location, eg `@8691`.
        (default 'Shanghai')
    quality_thresholds: specify a list of tuples, eg (number, 'color', 'name')
        *(default [(0, '#009966', 'Good'),
            (51, '#FFDE33', 'Moderate'),
            (101, '#FF9933', 'Sensitively Unhealthy'),
            (151, '#CC0033', 'Unhealthy'),
            (201, '#660099', 'Very Unhealthy'),
            (301, '#7E0023', 'Hazardous')])*
    thresholds: specify color thresholds to use (default {'aqi': True})

Notes:
    Your station may have individual scores for pollutants not listed below.
    See https://api.waqi.info/feed/@UID/?token=TOKEN (Replace UID and TOKEN)
    for a full list of placeholders to use.

Format placeholders:
    {aqi} air quality index
    {attributions_0_name} attribution name, there maybe more, change the 0
    {attributions_0_url} attribution url, there maybe more, change the 0
    {category} health risk category, eg Good, Moderate, Unhealthy, etc
    {city_geo_0} monitoring station latitude
    {city_geo_1} monitoring station longitude
    {city_name} monitoring station name
    {city_url} monitoring station url
    {dominentpol} dominant pollutant, eg pm25
    {idx} Unique ID for the city monitoring station, eg 7396
    {time} epoch timestamp, eg 1510246800
    {time_s} local timestamp, eg 2017-11-09 17:00:00
    {time_tz} local timezone, eg -06:00
    {iaqi_co}   individual score for pollutant carbon monoxide
    {iaqi_h}    individual score for pollutant h (?)
    {iaqi_no2}  individual score for pollutant nitrogen dioxide
    {iaqi_o3}   individual score for pollutant ozone
    {iaqi_pm25} individual score for pollutant particulates
                smaller than 2.5 μm in aerodynamic diameter
    {iaqi_pm10} individual score for pollutant particulates
                smaller than 10 μm in aerodynamic diameter
    {iaqi_pm15} individual score for pollutant particulates
                smaller than than 15 μm in aerodynamic diameter
    {iaqi_p}    individual score for pollutant particulates
    {iaqi_so2}  individual score for pollutant sulfur dioxide
    {iaqi_t}    individual score for pollutant t (?)
    {iaqi_w}    individual score for pollutant w (?)

    AQI denotes an air quality index. IQAI denotes an individual AQI score.
    Try https://en.wikipedia.org/wiki/Air_pollution#Pollutants for more
    information on the pollutants retrieved from your monitoring station.

format_datetime placeholders:
    key: epoch_placeholder, eg time, vtime
    value: % strftime characters to be translated, eg '%b %d' ----> 'Nov 11'

Color options:
    color_bad: print a color for error (if any) from the site

Color thresholds:
    xxx: print a color based on the value of `xxx` placeholder

Examples:
```
# show last updated time
air_quality {
    format = '{city_name}: {aqi} {category} - {time}'
    format_datetime = {'time': '%-I%P'}
}
```

@author beetleman, lasers
@license BSD

SAMPLE OUTPUT
{'color':'#009966', 'full_text':'Shanghai: 49 Good'}

aqi_moderate
{'color':'#FFDE33', 'full_text':'Shanghai: 65 Moderate'}

aqi_sensitively_unhealthy
{'color':'#FF9933', 'full_text':'Shanghai: 103 Sensitively Unhealthy'}

aqi_unhealthy
{'color':'#CC0033', 'full_text':'Shanghai: 165 Unhealthy'}

aqi_very_unhealthy
{'color':'#660099', 'full_text':'Shanghai: 220 Very Unhealthy'}

aqi_hazardous
{'color':'#7E0023', 'full_text':'Shanghai: 301 Hazardous'}
"""

from datetime import datetime
import socket
import select
import errno
import collections
import struct
import zlib
import json
import fcntl
import os
import re

if hasattr(collections, 'OrderedDict'):
    # python >= 2.7
    class WeechatDict(collections.OrderedDict):
        def __str__(self):
            return '{%s}' % ', '.join(
                ['%s: %s' % (repr(key), repr(self[key])) for key in self])
else:
    # python <= 2.6
    WeechatDict = dict

class Py3status:
    """
    """
    INIT_MESSAGE = "init {}\n"
    PASSWORD_MESSAGE = "pass {}\n"
    HDATA_MESSAGE = "hdata {} {}\n"
    INFOLIST_MESSAGE = "infolist {} {}\n"
    QUIT_MESSAGE = "quit\n"

    MODES = {
        'BY_SERVER': 'by_server',
        'BY_CHANNEL': 'by_channel',
        'SIMPLE_LIST': 'simple_list',
    }

    SOLID_SQUARE = '⬛'
    HOLLOW_SQUARE = '⬜'

    SOLID_CIRCLE = '⬤'
    HOLLOW_CIRCLE = '◯'

    SOLID_STAR = '✽'

    SINGLE_SPEECH_BUBBLE = '🗩'
    DOUBLE_SPEECH_BUBBLE = '🗪'
    MULTI_SPEECH_BUBBLE = '🗫'
    ANGER_BUBBLE = '🗯'
    THOUGHT_BUBBLE = '🗬'

    socket_path = "/home/jferg/.weechat/.weesocket"
    relay_pass = None
    proto = None
    format = "{hotlist_stoplights}"
    server_colors = { 'newcontext.slack.com': '#32c850',
                      'lusars.slack.com': '#ff66ff',
                      'seckc.slack.com': '#ff0000',
                      'bsideskc.slack.com': '#000099'}

    servers = []

    def post_config_hook(self):
        self.proto = Protocol()
        self.servers = self.server_colors.keys()

    def _get_hotbar_data(self):
        try:
            result = {}
            # Create a UDS socket
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(self.socket_path)
                # Set socket to non-blocking.
                fcntl.fcntl(sock, fcntl.F_SETFL, os.O_NONBLOCK)

                options = ['compression=off']

                if self.relay_pass:
                    options.append('password={}'.format(self.relay_pass.replace(',', '\,')))

                sock.sendall(self.INIT_MESSAGE.format(",".join(options)).encode('utf-8'))
                # sock.sendall(self.HDATA_MESSAGE.format("hotlist:gui_hotlist(*)", "").encode('utf-8'))
                sock.sendall(self.INFOLIST_MESSAGE.format("hotlist", "", "").encode('utf-8'))
                response = self._receive(sock)

                message = self.proto.decode(response)

                sock.sendall(self.QUIT_MESSAGE.encode('utf-8'))

                result = {'status': 'ok', 'message': message}

            return result

        except socket.error as e:
            return {'status': 'error', 'message': e}

    def _receive(self, sock):
        read_ready, _, _ = select.select([sock], [], [])

        buffer = b''

        if sock in read_ready:
            continue_recv = True

            while continue_recv:
                try:
                    buffer += sock.recv(1024)
                except socket.error as e:
                    if e.errno != errno.EWOULDBLOCK:
                        raise e
                    continue_recv = False

        length = struct.unpack('>i', buffer[0:4])[0]

        return buffer[0:length]

    def _organize(self, data):
        hotbar_items = data['message'].objects
        total_counts = [0, 0, 0]
        buffer_counts = {}
        server_counts = {}

        server_re = '^(' + ('|'.join(self.servers)) + r')\.(.*)'
        server_match = re.compile(server_re)

        for i in hotbar_items:
            for j in i.value['items']:
                buffer_name = j.get('buffer_name', 'unknown')
                matches = server_match.search(buffer_name)

                if matches:
                    buffer_server_name = matches.group(1)
                    buffer_short_name = matches.group(2)

                    if buffer_short_name not in buffer_counts:
                        buffer_counts[buffer_short_name] = [0, 0, 0]

                    if buffer_server_name not in server_counts:
                        server_counts[buffer_server_name] = [0, 0, 0]

                    for k in [0,1,2]:
                        total_counts[k] += j.get('count_0' + str(k), 0)
                        buffer_counts[buffer_short_name][k] += j.get('count_0' + str(k), 0)
                        server_counts[buffer_server_name][k] += j.get('count_0' + str(k), 0)

        data['message'] = {}

        data['total_counts'] = total_counts
        data['buffer_counts'] = buffer_counts
        data['server_counts'] = server_counts

        return data

    def _format(self, data):
        composite = []

        for server in self.servers:
            if server in data['server_counts']:
                if data['server_counts'][server][2]:
                    composite.append({'full_text': self.ANGER_BUBBLE, 'color': self.server_colors[server]})
                elif data['server_counts'][server][1] == 1:
                    composite.append({'full_text': self.SINGLE_SPEECH_BUBBLE, 'color': self.server_colors[server]})
                elif data['server_counts'][server][1] == 2:
                    composite.append({ 'full_text': self.DOUBLE_SPEECH_BUBBLE, 'color': self.server_colors[server]})
                elif data['server_counts'][server][1] > 2:
                    composite.append({ 'full_text': self.MULTI_SPEECH_BUBBLE, 'color': self.server_colors[server]})
                elif data['server_counts'][server][0]:
                    composite.append({ 'full_text': self.THOUGHT_BUBBLE, 'color': self.server_colors[server]})
                else:
                    composite.append({ 'full_text': self.SOLID_CIRCLE, 'color': self.server_colors[server]})     # Not sure we would ever get this case.
            else:
                composite.append({ 'full_text': self.SOLID_CIRCLE, 'color': self.server_colors[server]})

            composite.append({'full_text': ' '})

        composite.pop()
        data['composite'] = composite

        return data

    def weechat_hotbar(self):
        hotbar_data = self._get_hotbar_data()
        formatted_data = {}
        if hotbar_data:
            if hotbar_data.get("status") == "ok":
                organized_data = self._organize(hotbar_data)
                formatted_data = self._format(hotbar_data)
            elif hotbar_data.get("status") == "error":
                self.py3.error(formatted_data.get("data"))

        return formatted_data

# Shamelessly stolen from
# https://github.com/weechat/qweechat/blob/master/qweechat/weechat/protocol.py
# because there's no reason to reinvent the wheel.

class WeechatObject:
    def __init__(self, objtype, value, separator='\n'):
        self.objtype = objtype
        self.value = value
        self.separator = separator
        self.indent = '  ' if separator == '\n' else ''
        self.separator1 = '\n%s' % self.indent if separator == '\n' else ''

    def _str_value(self, v):
        if type(v) is str and v is not None:
            return '\'%s\'' % v
        return str(v)

    def _str_value_hdata(self):
        lines = ['%skeys: %s%s%spath: %s' % (self.separator1,
                                             str(self.value['keys']),
                                             self.separator,
                                             self.indent,
                                             str(self.value['path']))]
        for i, item in enumerate(self.value['items']):
            lines.append('  item %d:%s%s' % (
                (i + 1), self.separator,
                self.separator.join(
                    ['%s%s: %s' % (self.indent * 2, key,
                                   self._str_value(value))
                     for key, value in item.items()])))
        return '\n'.join(lines)

    def _str_value_infolist(self):
        lines = ['%sname: %s' % (self.separator1, self.value['name'])]
        for i, item in enumerate(self.value['items']):
            lines.append('  item %d:%s%s' % (
                (i + 1), self.separator,
                self.separator.join(
                    ['%s%s: %s' % (self.indent * 2, key,
                                   self._str_value(value))
                     for key, value in item.items()])))
        return '\n'.join(lines)

    def _str_value_other(self):
        return self._str_value(self.value)

    def __str__(self):
        self._obj_cb = {
            'hda': self._str_value_hdata,
            'inl': self._str_value_infolist,
        }
        return '%s: %s' % (self.objtype,
                           self._obj_cb.get(self.objtype,
                                            self._str_value_other)())


class WeechatObjects(list):
    def __init__(self, separator='\n'):
        self.separator = separator

    def __str__(self):
        return self.separator.join([str(obj) for obj in self])


class WeechatMessage:
    def __init__(self, size, size_uncompressed, compression, uncompressed,
                 msgid, objects):
        self.size = size
        self.size_uncompressed = size_uncompressed
        self.compression = compression
        self.uncompressed = uncompressed
        self.msgid = msgid
        self.objects = objects

    def __str__(self):
        if self.compression != 0:
            return 'size: %d/%d (%d%%), id=\'%s\', objects:\n%s' % (
                self.size, self.size_uncompressed,
                100 - ((self.size * 100) // self.size_uncompressed),
                self.msgid, self.objects)
        else:
            return 'size: %d, id=\'%s\', objects:\n%s' % (self.size,
                                                          self.msgid,
                                                          self.objects)


class Protocol:
    """Decode binary message received from WeeChat/relay."""

    def __init__(self):
        self._obj_cb = {
            'chr': self._obj_char,
            'int': self._obj_int,
            'lon': self._obj_long,
            'str': self._obj_str,
            'buf': self._obj_buffer,
            'ptr': self._obj_ptr,
            'tim': self._obj_time,
            'htb': self._obj_hashtable,
            'hda': self._obj_hdata,
            'inf': self._obj_info,
            'inl': self._obj_infolist,
            'arr': self._obj_array,
        }

    def _obj_type(self):
        """Read type in data (3 chars)."""
        if len(self.data) < 3:
            self.data = ''
            return ''
        objtype = self.data[0:3].decode()
        self.data = self.data[3:]
        return objtype

    def _obj_len_data(self, length_size):
        """Read length (1 or 4 bytes), then value with this length."""
        if len(self.data) < length_size:
            self.data = ''
            return None
        if length_size == 1:
            length = struct.unpack('B', self.data[0:1])[0]
            self.data = self.data[1:]
        else:
            length = self._obj_int()
        if length < 0:
            return None
        if length > 0:
            value = self.data[0:length]
            self.data = self.data[length:]
        else:
            value = ''
        # This code is bad and I feel bad.
        return "".join(map(chr, list(value)))
        # return str(value, encoding='ascii')

    def _obj_char(self):
        """Read a char in data."""
        if len(self.data) < 1:
            return 0
        value = struct.unpack('b', self.data[0:1])[0]
        self.data = self.data[1:]
        return value

    def _obj_int(self):
        """Read an integer in data (4 bytes)."""
        if len(self.data) < 4:
            self.data = ''
            return 0
        value = struct.unpack('>i', self.data[0:4])[0]
        self.data = self.data[4:]
        return value

    def _obj_long(self):
        """Read a long integer in data (length on 1 byte + value as string)."""
        value = self._obj_len_data(1)
        if value is None:
            return None
        return int(value)

    def _obj_str(self):
        """Read a string in data (length on 4 bytes + content)."""
        value = self._obj_len_data(4)
        if value is None:
            return None
        return str(value)

    def _obj_buffer(self):
        """Read a buffer in data (length on 4 bytes + data)."""
        return self._obj_len_data(4)

    def _obj_ptr(self):
        """Read a pointer in data (length on 1 byte + value as string)."""
        value = self._obj_len_data(1)
        if value is None:
            return None
        return '0x%s' % str(value)

    def _obj_time(self):
        """Read a time in data (length on 1 byte + value as string)."""
        value = self._obj_len_data(1)
        if value is None:
            return None
        return int(str(value))

    def _obj_hashtable(self):
        """
        Read a hashtable in data
        (type for keys + type for values + count + items).
        """
        type_keys = self._obj_type()
        type_values = self._obj_type()
        count = self._obj_int()
        hashtable = WeechatDict()
        for _ in range(count):
            key = self._obj_cb[type_keys]()
            value = self._obj_cb[type_values]()
            hashtable[key] = value
        return hashtable

    def _obj_hdata(self):
        """Read a hdata in data."""
        path = self._obj_str()
        keys = self._obj_str()
        count = self._obj_int()
        list_path = path.split('/') if path else []
        list_keys = keys.split(',') if keys else []
        keys_types = []
        dict_keys = WeechatDict()
        for key in list_keys:
            items = key.split(':')
            keys_types.append(items)
            dict_keys[items[0]] = items[1]
        items = []
        for _ in range(count):
            item = WeechatDict()
            item['__path'] = []
            pointers = []
            for _ in enumerate(list_path):
                pointers.append(self._obj_ptr())
            for key, objtype in keys_types:
                item[key] = self._obj_cb[objtype]()
            item['__path'] = pointers
            items.append(item)
        return {
            'path': list_path,
            'keys': dict_keys,
            'count': count,
            'items': items,
        }

    def _obj_info(self):
        """Read an info in data."""
        name = self._obj_str()
        value = self._obj_str()
        return (name, value)

    def _obj_infolist(self):
        """Read an infolist in data."""
        name = self._obj_str()
        count_items = self._obj_int()
        items = []
        for _ in range(count_items):
            count_vars = self._obj_int()
            variables = WeechatDict()
            for _ in range(count_vars):
                var_name = self._obj_str()
                var_type = self._obj_type()
                var_value = self._obj_cb[var_type]()
                variables[var_name] = var_value
            items.append(variables)
        return {
            'name': name,
            'items': items
        }

    def _obj_array(self):
        """Read an array of values in data."""
        type_values = self._obj_type()
        count_values = self._obj_int()
        values = []
        for _ in range(count_values):
            values.append(self._obj_cb[type_values]())
        return values

    def decode(self, data, separator='\n'):
        """Decode binary data and return list of objects."""
        self.data = data
        size = len(self.data)
        size_uncompressed = size
        uncompressed = None
        # uncompress data (if it is compressed)
        compression = struct.unpack('b', self.data[4:5])[0]
        if compression:
            uncompressed = zlib.decompress(self.data[5:])
            size_uncompressed = len(uncompressed) + 5
            uncompressed = '%s%s%s' % (struct.pack('>i', size_uncompressed),
                                       struct.pack('b', 0), uncompressed)
            self.data = uncompressed
        else:
            uncompressed = self.data[:]
        # skip length and compression flag
        self.data = self.data[5:]
        # read id
        msgid = self._obj_str()
        if msgid is None:
            msgid = ''
        # read objects
        objects = WeechatObjects(separator=separator)
        while len(self.data) > 0:
            objtype = self._obj_type()
            value = self._obj_cb[objtype]()
            objects.append(WeechatObject(objtype, value, separator=separator))
        return WeechatMessage(size, size_uncompressed, compression,
                              uncompressed, msgid, objects)

if __name__ == "__main__":
    """
    Run module in test mode.
    """
    from py3status.module_test import module_test

    module_test(Py3status)
