# Copyright 2025 Mike Iacovacci <ascendr@linuxmail.org>
# Copyright 2025 Jonathan Deeds
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import struct
import logging
import time
from datetime import datetime
from chirp import chirp_common, directory, memmap
from chirp import bitwise, errors
from chirp.settings import RadioSetting, RadioSettingGroup, \
    RadioSettingValueInteger, RadioSettingValueList, \
    RadioSettingValueBoolean, RadioSettingValueString, \
    RadioSettings, RadioSettingValueMap, RadioSettingSubGroup

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
# seekto 0x0050;
struct{
    char        soft_ver[7];
    u8          pad_0x57;
    char        hard_ver[6];
    u8          pad_0x5e_f[2];
    char        last_prog[16];
} dev_info;

# seekto 0x0080;
struct{
    lbcd        rx_freq[4];
    lbcd        tx_freq[4];
    bbcd        rx_tone[2];
    bbcd        tx_tone[2];
    u8          unk_0x0d[4];
    u8          power:2,
                bandwidth:1,
                unk1_0x10:3,
                invert:1,
                talkaround:1;
    u8          pttid_mode:4,
                sqlch_mode:4;
    u8          signaling:4,
                jump_mode:4;
    u8          unk_0x13:2,
                launch_banned:1,
                unk1_0x13:5;
    u8          unk_0x14_18[5];
    u8          dtmf;
    u8          twotone;
    u8          fivetone;
    u8          mdc;
    u8          unk_0x1d[1];
    u8          emerg_sys;
    u8          unk_0x1f[1];
    char        name[16];
} memory[640];

# seekto 0x7980;
struct{
    u8          band_a_wrkmode;
    u8          band_b_wrkmode;
    u8          unk_0x82_0x85[4];
    u8          band_a_workzone;
    u8          band_b_workzone;
    u8          backlight_tm;
    u8          tone_lvl;
    u8          band_a_chandisp:4,
                band_b_chandisp:4;
    u8          dbl_waiting;
    u8          main_band;
    u8          squelch;
    u8          vox_lvl;
    u8          vox_dly_detect;
    u8          power_save_off;
    u8          power_save_time;
    u8          lone_wrk_remind;
    u8          lone_wrk_resp;
    u8          apo;
    u8          tot;
    u8          tot_alert;
    u8          unk_0x97;
    u8          gps_zone;
    u8          unk_0x99;
    u8          hz1750;
    u8          unk_0x9b_9d[3];
    u8          noaa_chan;
    u8          unk_0x_9f;
    u8          vox:1,
                aprs:1,
                alone_worker:1,
                falling_alarm:1,
                voice_announce:2,
                unk_0xa0:1,
                busy_lock:1;
    u8          auto_keypad;
    u8          tone;
    u8          unk_0xa3;
    u8          gps;
    u8          power_on_char:1,
                power_on_volt:1,
                language:1,
                wx:1,
                eng_mode:1,
                unk_0xa5:3;
    u8          tail_mode:3,
                noaa:1,
                disp_reverse:1,
                unk_0xa6:2,
                enhance_func:1;
} settings;

# seekto 0x79b0;
struct{
    u8      pf1_short;
    u8      pf2_short;
    u8      pf1_long;
    u8      pf2_long;
}prog_key;

# seekto 0x79c0;
struct{
    u8      power_on_pwd[8];
    u8      program_pwd[8];
    u8      power_on_char[8];
} power_on;

# seekto 0x7a20;
struct{
    lbit      bitfield[640];
} chan_empty;

# seekto 0x8102;
struct{
    lbcd        upper_freq[2];
    u8          sc_pad[2];
    lbcd        lower_freq[2];
} scan_freq;

# seekto 0x8180;
struct{
    u8      scan_mode;
    u8      flyback;
    u8      rx_recovery;
    u8      tx_recovery;
    u8      channel_rtn;
    u8      priority;
    u8      unk_0x8186[1];
    u8      prio_scan_chan;
    u8      scan_range;
} scan_menu;

# seekto 0x81a0;
struct{
    lbit      bitfield[640];
} scan_skip;

# seekto 0x8200;
struct{
    u8      dtmf_ani;
    u8      sending_rate;
    u8      first_tm_code;
    u8      precarrier_tm;
    u8      delay_tm;
    u8      ptt_pause_tm;
    u8      dtmf_st;
    u8      auto_reset_tm;
    u8      sepr_opts;
    u8      group_num;
    u8      decode_resp;
    u8      unk_0xb_f[5];
    u8      self_id[3];
    u8      unk_0x13_17[5];
    u8      ptt_id[16];
    u8      ptt_id_offline[16];
    u8      stun[11];
    u8      pad_0x43_47[5];
    u8      kill[11];
}dtmf;

# seekto 0x8260;
struct{
    u8      entry[16];
} dtmf_list[16];

# seekto 0x9e00;
struct{
    char        selfid[6];
    u8          self_ssid;
    u8          self_pad;
    char        targetid[6];
    u8          target_ssid;
    u8          target_pad;
    u8          precarrier_tm;
    u8          code_dly_tm;

} aprs_menu;

# seekto 0x9e18;
struct{
    char        entry[6];
    u8          ssid;
    u8          unused;
} ssid_tbl[8];

# seekto 0xa010;
struct{
    u8          code;
    u8          unused2;
    char        name[14];
} contacts[80];
"""

ADDRS = [0x000000, 0x100000, 0x200000, 0x300000,
         0x400000, 0x500000, 0x600000, 0x700000,
         0x800000, 0x900000, 0xa00000]

BLK_SZ = 0x1000


def raw_send(serial, data, exlen):
    serial.write(data)
    return (serial.read(exlen))


def wakeup(serial):
    cmd = struct.pack('>QLL', 0, 0, 0xffffffff)
    raw_send(serial, cmd, 0)
    time.sleep(.5)
    resp = raw_send(serial, cmd, 1)
    if len(resp) != 1 or resp != b'\x41':
        err = f"Radio Wakeup error expected 0x41 got {resp}"
        LOG.error(err)
        raise errors.RadioError(err)


def exit_prog(serial, xor):
    ba = [b ^ xor for b in b'END\x00']
    try:
        resp = raw_send(serial, bytes(ba), 1)
        if len(resp) > 0 and (resp[0] ^ xor) != 0x41:
            err = f"Exit Prog expect 0x41 got {resp.hex()}"
            LOG.error(err)
    except Exception as e:
        LOG.error(f"Exit prog error: {e}")


def do_init(serial, xor):
    cmd = b'PROGRAM' + bytes([xor])
    resp = raw_send(serial, cmd, 1)
    if (resp[0] ^ xor) != 0x41:
        err = f"Init Error expected 0x41 got {resp}"
        LOG.error(err)
        raise errors.RadioError(err)
    xb = xor ^ 0xff
    cmd = bytes([xb] * 8)
    resp = raw_send(serial, cmd, 1)
    if (resp[0] ^ xor) != 0x41:
        err = f"Init Error expected 0x41 got {resp}"
        LOG.error(err)
        raise errors.RadioError(err)
    xs = [(xor ^ ord(c)) for c in 'INFORMATION']
    resp = raw_send(serial, bytes(xs), 16)
    id = [chr(b ^ xor) for b in resp[:6]]
    if "".join(id) != 'BF-5RH':
        err = f"Radio Mismatch got {id}"
        LOG.error(err)
        raise errors.RadioError(err)


def setup_for_read(serial, xor):
    resp = raw_send(serial, bytes(0x52 ^ xor), 1)
    if len(resp) < 1 or (resp[0] ^ xor) != 0x41:
        err = f"setup_for_read Error expected 0x41 got 0x{resp.hex()}"
        LOG.error(err)
        raise errors.RadioError(err)


def read_block(serial, xor, addr, blk_len):
    i_cmd = (0x52000000 + addr) ^ (0x01010101 * xor)
    cmd = struct.pack('>L', i_cmd)
    resp = raw_send(serial, cmd, blk_len + 4)
    i_resp = struct.unpack('>L', resp[:4])[0]
    if i_resp != ((0x57000000 + addr) ^ (0x01010101 * xor)):
        err = "Read block echo failed"
        LOG.error(err)
        raise errors.RadioError(err)
    return resp[4:]


def setup_for_write(serial, xor):
    resp = raw_send(serial, bytes(0x57 ^ xor), 1)
    if len(resp) < 1 or (resp[0] ^ xor) != 0x41:
        err = f"setup_for_write Error expected 0x41 got 0x{resp.hex()}"
        LOG.error(err)
        raise errors.RadioError(err)


def write_block(serial, xor, addr, data, blk_len):
    i_cmd = (0x57000000 + addr) ^ (0x01010101 * xor)
    block_end_cmd = 0x01010101 * xor
    cmd = struct.pack('>L', i_cmd)
    resp = raw_send(serial, cmd + data, 0)
    resp = raw_send(serial, block_end_cmd, 1)
    if len(resp) < 1 or (resp[0] ^ xor) != 0x41:
        err = f"Write block ack failed expect 0x41 got {resp[0]}"
        LOG.error(err)
        raise errors.RadioError(err)
    return blk_len


def do_download(radio):
    data = b''
    try:
        xor = 0x00
        serial = radio.pipe
        serial.timeout = 5.0
        status = chirp_common.Status()
        status.msg = "Connecting to Radio..."
        radio.status_fn(status)
        wakeup(serial)
        do_init(serial, xor)
        setup_for_read(serial, xor)
        status.max = len(ADDRS) * BLK_SZ
        status.msg = "Downloading..."
        for addr in ADDRS:
            resp = read_block(serial, xor, addr, BLK_SZ)
            da = [b ^ xor for b in resp]
            data += bytes(da)
            status.cur += len(resp)
            radio.status_fn(status)
    except errors.RadioError:
        raise
    except Exception as e:
        LOG.error(f"Error downloading {e}")
    finally:
        exit_prog(serial, xor)
    return memmap.MemoryMapBytes(data)


def do_upload(radio):
    try:
        fmt = "%Y.%m.%d %H:%M"
        prog_dt = datetime.now().strftime(fmt)
        radio._memobj.dev_info.last_prog = prog_dt
        xor = 0x00
        serial = radio.pipe
        serial.timeout = 5.0
        status = chirp_common.Status()
        status.msg = "Connecting to Radio..."
        radio.status_fn(status)
        wakeup(serial)
        do_init(serial, xor)
        setup_for_write(serial, xor)
        status.max = len(ADDRS) * BLK_SZ
        status.msg = "Uploading..."
        for i, addr in enumerate(ADDRS):
            si = BLK_SZ * i
            ei = BLK_SZ * (i+1)
            data = radio._mmap[si:ei]
            enc_data = bytes([b ^ xor for b in data])
            resp = write_block(serial, xor, addr, enc_data, BLK_SZ)
            status.cur += len(resp)
            radio.status_fn(status)
    except errors.RadioError:
        raise
    except Exception as e:
        LOG.error(f"Error uploading {e}")
    finally:
        exit_prog(serial, xor)


def null_terminated_string(array_data):
    chars = []
    for c in array_data:
        ch = str(c)
        if ch == '\0':
            break
        chars.append(ch)
    return "".join(chars)


@directory.register
class BF5RHProGPS(chirp_common.CloneModeRadio):
    """Baofeng BF-5RH Pro GPS"""
    VENDOR = "Baofeng"
    MODEL = "BF-5RH Pro GPS"
    BAUD_RATE = 19200
    POWER_LEVELS = [chirp_common.PowerLevel("Low",  watts=1.00),
                    chirp_common.PowerLevel("Medium", watts=5.00),
                    chirp_common.PowerLevel("High", watts=10.00)]
    VALID_MODES = ["NFM", "FM"]
    VALID_BANDS = [(108000000, 174000000), (220000000, 260000000),
                   (350000000, 390000000), (400000000, 520000000)]
    VALID_TONES = (63.0, ) + chirp_common.TONES
    VALID_DCS = (17, 50, 645) + chirp_common.DTCS_CODES
    VALID_CHARSET = "".join(chr(i) for i in range(32, 127))
    VALID_DTMF = [str(i) for i in range(0, 10)] + \
        ["A", "B", "C", "D", "*", "#"] + [' ']
    ASCII_NUM = [str(i) for i in range(10)] + [' ']

    SSID_OPMAP = [('None', 255), ('0', 0), ('-1', 1), ('-2', 2),
                  ('-3', 3), ('-4', 4), ('-5', 5), ('-6', 6),
                  ('-7', 7), ('-8', 8), ('-9', 9), ('-10', 10),
                  ('-11', 11), ('-12', 12), ('-13', 13),
                  ('-14', 14), ('-15', 15)]

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = False
        rf.has_name = True
        rf.valid_name_length = 16
        rf.valid_characters = self.VALID_CHARSET
        rf.has_offset = True
        rf.has_mode = True
        rf.has_dtcs = True
        rf.has_rx_dtcs = True
        rf.has_dtcs_polarity = True
        rf.has_ctone = True
        rf.has_cross = True
        rf.valid_tones = self.VALID_TONES
        rf.can_odd_split = False
        rf.can_delete = True
        rf.valid_modes = self.VALID_MODES
        rf.valid_duplexes = ["", "-", "+", "off"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = [
            "Tone->DTCS",
            "DTCS->Tone",
            "->Tone",
            "Tone->Tone",
            "->DTCS",
            "DTCS->",
            "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_skips = ["", "S"]
        rf.valid_bands = self.VALID_BANDS
        rf.memory_bounds = (1, 640)
        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def sync_in(self):
        try:
            data = do_download(self)
        except Exception as e:
            err = f'Error during download {e}'
            LOG.error(err)
            raise errors.RadioError(err)
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        try:
            do_upload(self)
        except Exception as e:
            raise errors.RadioError(f"Error during upload {e}")

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _mem = self._memobj.memory[number-1]
        mem.freq = int(_mem.rx_freq) * 10
        if self.get_empty(number - 1):
            mem.empty = True
            return mem

        mem.name = null_terminated_string(_mem.name).ljust(16)

        mem.power = self.POWER_LEVELS[_mem.power]
        mem.mode = self.VALID_MODES[_mem.bandwidth]
        mem.skip = 'S' if self.get_skip(number - 1) else ""

        if int(_mem.tx_freq) == int(_mem.rx_freq):
            mem.duplex = ''
            mem.offset = 0
        elif int(_mem.tx_freq) == 0:
            mem.duplex = 'off'
            mem.offset = 0
        elif int(_mem.tx_freq) > int(_mem.rx_freq):
            mem.duplex = '+'
            mem.offset = (int(_mem.tx_freq) - int(_mem.rx_freq)) * 10
        elif int(_mem.rx_freq) > int(_mem.tx_freq):
            mem.duplex = '-'
            mem.offset = ((int(_mem.rx_freq) - int(_mem.tx_freq)) * 10)

        self.get_tones(_mem, mem)

        mem.extra = RadioSettingGroup("Extra", "extra")

        rstype = RadioSettingValueBoolean(_mem.invert)
        rs = RadioSetting("invert", "TX Invert", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueBoolean(_mem.talkaround)
        rs = RadioSetting("talkaround", "Talkaround", rstype)
        mem.extra.append(rs)

        _options = [('Off', 0), ('PTT BOT', 1), ('PTT EOT', 2),
                    ('PTT Both', 3), ('5-Tone BOT', 4),
                    ('5-Tone EOT', 8), ('5-Tone Both', 12)]
        rstype = RadioSettingValueMap(_options, _mem.pttid_mode)
        rs = RadioSetting("pttid_mode", "PTT/5-Tone ID", rstype)
        mem.extra.append(rs)

        _options = [('Off', 0), ('CTDCS', 1), ('Optional', 2),
                    ('Both', 3)]
        rstype = RadioSettingValueMap(_options, _mem.sqlch_mode)
        rs = RadioSetting("sqlch_mode", "Squelch Mode", rstype)
        mem.extra.append(rs)

        _options = [('Off', 0), ('DTMF', 2), ('2-Tone', 4),
                    ('5-Tone', 6), ('MDC', 8), ('BIIS', 12)]
        rstype = RadioSettingValueMap(_options, _mem.signaling)
        rs = RadioSetting("signaling", "Signaling", rstype)
        mem.extra.append(rs)

        _options = [('Off', 0), ('Normal', 1), ('Strict', 2)]
        rstype = RadioSettingValueMap(_options, _mem.jump_mode)
        rs = RadioSetting("jump_mode", "Jump Freq.", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueBoolean(_mem.launch_banned)
        rs = RadioSetting("launch_banned", "Launch Banned", rstype)
        mem.extra.append(rs)

        _options = [str(i) for i in range(16+1)]
        rstype = RadioSettingValueList(options=_options,
                                       current_index=int(_mem.dtmf))
        rs = RadioSetting("dtmf", "DTMF Index", rstype)
        mem.extra.append(rs)

        rstype = RadioSettingValueList(options=_options,
                                       current_index=int(_mem.twotone))
        rs = RadioSetting("twotone", "2-Tone Index", rstype)
        mem.extra.append(rs)

        _options = [str(i) for i in range(5+1)]
        rstype = RadioSettingValueList(options=_options,
                                       current_index=int(_mem.mdc))
        rs = RadioSetting("mdc", "MDC Index", rstype)
        mem.extra.append(rs)

        _options = [str(i) for i in range(10+1)]
        rstype = RadioSettingValueList(options=_options,
                                       current_index=int(_mem.emerg_sys))
        rs = RadioSetting("emerg_sys", "Emergency System", rstype)
        mem.extra.append(rs)

        return mem

    def set_memory(self, mem):

        _mem = self._memobj.memory[mem.number - 1]

        if mem.empty:
            self.set_empty(mem.number - 1, 1)
            _mem.fill_raw(b'\x00')
            return

        _mem.rx_freq = mem.freq // 10

        if self.get_empty(mem.number - 1):
            # new memory
            self.set_empty(mem.number - 1, 0)
            mem.duplex == ''
            _mem.tx_freq.set_value(int(_mem.rx_freq))
            _mem.power = 1

        _name = [c for c in mem.name]
        if len(_name) < 16:
            _name = _name + [' '] * (16 - len(_name))
        _mem.name = _name

        _skip = 1 if mem.skip == 'S' else 0
        self.set_skip(mem.number - 1, _skip)

        _mem.bandwidth = self.VALID_MODES.index(mem.mode)
        self.set_tone(_mem, mem)

        if mem.duplex == '+':
            _mem.tx_freq = (mem.freq + mem.offset) // 10
        elif mem.duplex == '-':
            _mem.tx_freq = (mem.freq - mem.offset) // 10
        elif mem.duplex == '':
            _mem.tx_freq.set_value(int(_mem.rx_freq))
        elif mem.duplex == 'off':
            _mem.tx_freq.set_value(0)

        for setting in mem.extra:
            setattr(_mem, setting.get_name(), setting.value)

    def get_tones(self, _mem, mem):
        _memrxtone = int(_mem.rx_tone)
        msb = _mem.rx_tone.get_raw()[0]
        if _memrxtone == 16665 or _memrxtone == 0:
            rxtone = ("", 0, None)
        elif 0x80 <= msb < 0xc0:
            # DCS Normal
            rxtone = ("DTCS", _memrxtone % 8000, "N")
        elif msb >= 0xc0:
            # DCS Inverted
            rxtone = ("DTCS", _memrxtone % 12000, "R")
        else:
            # CTCSS
            rxtone = ("Tone",  _memrxtone / 10, None)
        _memtxtone = int(_mem.tx_tone)
        msb = _mem.tx_tone.get_raw()[0]
        if _memtxtone == 16665 or _memtxtone == 0:
            txtone = ("", 0, None)
        elif 0x80 <= msb < 0xc0:
            # DCS Normal
            txtone = ("DTCS",  _memtxtone % 8000, "N")
        elif msb >= 0xc0:
            # DCS Inverted
            txtone = ("DTCS",  _memtxtone % 12000, "R")
        else:
            # CTCSS
            txtone = ("Tone",  _memtxtone / 10, None)
        chirp_common.split_tone_decode(mem, txtone, rxtone)

    def set_tone(self, _mem, mem):
        ((txmode, txval, txpol),
         (rxmode, rxval, rxpol)) = chirp_common.split_tone_encode(mem)
        if txmode == "":
            _mem.tx_tone.set_raw(b'\xff\xff')
        if rxmode == "":
            _mem.rx_tone.set_raw(b'\xff\xff')
        if txmode == "Tone":
            _mem.tx_tone = int(txval * 10)
        if rxmode == "Tone":
            _mem.rx_tone = int(rxval * 10)
        if txmode == "DTCS" and txpol == "N":
            _mem.tx_tone = int(txval + 8000)
        if rxmode == "DTCS" and rxpol == "N":
            _mem.rx_tone = int(rxval + 8000)
        if txmode == "DTCS" and txpol == "R":
            msb = (txval // 100) + 0xc0
            lsb = int("%02i" % (txval % 100), 16)
            _mem.tx_tone.set_raw(bytes([msb, lsb]))
        if rxmode == "DTCS" and rxpol == "R":
            msb = (rxval // 100) + 0xc0
            lsb = int("%02i" % (rxval % 100), 16)
            _mem.rx_tone.set_raw(bytes([msb, lsb]))

    def get_skip(self, chan_n):
        return self._memobj.scan_skip['bitfield'][chan_n].get_value()

    def set_skip(self, chan_n, value):
        self._memobj.scan_skip['bitfield'][chan_n].set_value(value)

    def get_empty(self, chan_n):
        return self._memobj.chan_empty['bitfield'][chan_n].get_value()

    def set_empty(self, chan_n, value):
        self._memobj.chan_empty['bitfield'][chan_n].set_value(value)

    def get_settings(self):
        _dev_info = self._memobj.dev_info
        _settings = self._memobj.settings
        _prog_key = self._memobj.prog_key
        _dtmf = self._memobj.dtmf
        _dtmf_list = self._memobj.dtmf_list
        _ssid_tbl = self._memobj.ssid_tbl
        _scan_freq = self._memobj.scan_freq
        _scan_menu = self._memobj.scan_menu
        _aprs_menu = self._memobj.aprs_menu
        _contacts = self._memobj.contacts

        def _idx_or_default(setting, _list, default):
            try:
                _list[setting]
                return setting
            except IndexError:
                return default

        info = RadioSettingGroup("info", "Device Info")
        group = RadioSettings(info)

        _current = "".join(str(c) for c in _dev_info.soft_ver)
        rs = RadioSettingValueString(minlength=7, maxlength=7,
                                     current=_current,
                                     charset=self.VALID_CHARSET,
                                     autopad=False)
        rs.set_mutable(False)
        rset = RadioSetting("dev_info.soft_ver", "Software Version", rs)
        info.append(rset)

        _current = "".join(str(c) for c in _dev_info.hard_ver)
        rs = RadioSettingValueString(minlength=6, maxlength=6,
                                     current=_current,
                                     charset=self.VALID_CHARSET,
                                     autopad=False)
        rs.set_mutable(False)
        rset = RadioSetting("dev_info.hard_ver", "Hardware Version", rs)
        info.append(rset)

        _current = "".join(str(c) for c in _dev_info.last_prog)
        rs = RadioSettingValueString(minlength=16, maxlength=16,
                                     current=_current,
                                     charset=self.VALID_CHARSET,
                                     autopad=False)
        rs.set_mutable(False)
        rset = RadioSetting("dev_info.last_prog", "Last Programmed", rs)
        info.append(rset)

        settings = RadioSettingGroup("settings", "Settings")
        group.append(settings)

        rs = RadioSettingValueInteger(minval=0, maxval=9,
                                      current=_settings.squelch, step=1)
        rset = RadioSetting("settings.squelch", "Squelch Level", rs)
        settings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.vox, mem_vals=(0, 1))
        rset = RadioSetting("settings.vox", "VOX", rs)
        settings.append(rset)

        a = ['n/a'] + [str(i/10) for i in range(10, 101, 5)]
        b = [0] + list(range(10, 100+1, 5))
        _opmap = list(zip(a, b))
        rs = RadioSettingValueMap(_opmap, _settings.vox_dly_detect)
        rset = RadioSetting("settings.vox_dly_detect",
                            "VOX Delay Detect(s)", rs)
        settings.append(rset)

        rs = RadioSettingValueInteger(minval=0, maxval=9,
                                      current=_settings.vox_lvl, step=1)
        rset = RadioSetting("settings.vox_lvl", "Vox Level", rs)
        settings.append(rset)

        _opmap = [('1', 0), ('2', 1), ('3', 2), ('4', 3), ('5', 4)]
        rs = RadioSettingValueMap(_opmap, _settings.tone_lvl)
        rset = RadioSetting("settings.tone_lvl", "Tone Level", rs)
        settings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.wx, mem_vals=(0, 1))
        rset = RadioSetting("settings.wx", "WX", rs)
        settings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.noaa, mem_vals=(0, 1))
        rset = RadioSetting("settings.noaa", "NOAA", rs)
        settings.append(rset)

        _options = [str(i) for i in range(1, 10+1)]
        rs = RadioSettingValueList(
            _options, current_index=_settings.noaa_chan)
        rset = RadioSetting("settings.noaa_chan",
                            "NOAA Channel", rs)
        settings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.gps, mem_vals=(0, 1))
        rset = RadioSetting("settings.gps", "GPS", rs)
        settings.append(rset)

        _options = [str(i) for i in range(-12, 13, 1)]
        rs = RadioSettingValueList(
            _options, current_index=_settings.gps_zone)
        rset = RadioSetting("settings.gps_zone",
                            "GPS Zone", rs)
        settings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.aprs, mem_vals=(0, 1))
        rset = RadioSetting("settings.aprs", "APRS", rs)
        settings.append(rset)

        _options = ['Off', 'Chinese', 'English']
        rs = RadioSettingValueList(
            _options, current_index=_settings.voice_announce)
        rset = RadioSetting("settings.voice_announce",
                            "Voice Announce", rs)
        settings.append(rset)

        _options = ['Freq', 'Name', 'Number', 'Freq. + Name']
        rs = RadioSettingValueList(
            _options, current_index=_settings.band_a_chandisp)
        rset = RadioSetting("settings.band_a_chandisp",
                            "Band A Chan. Display", rs)
        settings.append(rset)

        _options = ['Freq', 'Name', 'Number', 'Freq. + Name']
        rs = RadioSettingValueList(
            _options, current_index=_settings.band_b_chandisp)
        rset = RadioSetting("settings.band_b_chandisp",
                            "Band B Chan. Display", rs)
        settings.append(rset)

        _options = ['A', 'B']
        rs = RadioSettingValueList(
            _options, current_index=_settings.main_band)
        rset = RadioSetting("settings.main_band",
                            "Main Band", rs)
        settings.append(rset)

        _options = ['VFO', 'MR']
        rs = RadioSettingValueList(
            _options, current_index=_settings.band_a_wrkmode)
        rset = RadioSetting("settings.band_a_wrkmode",
                            "Band A Mode", rs)
        settings.append(rset)

        _options = ['VFO', 'MR']
        rs = RadioSettingValueList(
            _options, current_index=_settings.band_b_wrkmode)
        rset = RadioSetting("settings.band_b_wrkmode",
                            "Band B Mode", rs)
        settings.append(rset)

        _options = ['1', '2']
        rs = RadioSettingValueList(
            _options, current_index=_settings.band_a_workzone)
        rset = RadioSetting("settings.band_a_workzone",
                            "Band A Zone", rs)
        settings.append(rset)

        _options = ['1', '2']
        rs = RadioSettingValueList(
            _options, current_index=_settings.band_b_workzone)
        rset = RadioSetting("settings.band_b_workzone",
                            "Band B Zone", rs)
        settings.append(rset)

        a = ['always'] + [str(i) for i in range(5, 31)]
        b = [0] + [i for i in range(5, 31)]
        _opmap = list(zip(a, b))
        rs = RadioSettingValueMap(_opmap, _settings.backlight_tm)
        rset = RadioSetting("settings.backlight_tm", "Backlight Time(s)", rs)
        settings.append(rset)

        _options = ['Off', '1:1', '1:2', '1:4']
        rs = RadioSettingValueList(
            _options, current_index=_settings.power_save_off)
        rset = RadioSetting("settings.power_save_off",
                            "Power Save Off", rs)
        settings.append(rset)

        _options = ['5', '10', '15', '20', '25']
        rs = RadioSettingValueList(
            _options, current_index=_settings.power_save_time)
        rset = RadioSetting("settings.power_save_time",
                            "Power Save Time", rs)
        settings.append(rset)

        _options = ['Off', 'Dual', 'Single']
        rs = RadioSettingValueList(
            _options, current_index=_settings.dbl_waiting)
        rset = RadioSetting("settings.dbl_waiting",
                            "Double Waiting (s)", rs)
        settings.append(rset)

        _options = ['Off', '30', '60', '120', '240', '480']
        rs = RadioSettingValueList(
            _options, current_index=_settings.apo)
        rset = RadioSetting("settings.apo",
                            "APO (min)", rs)
        settings.append(rset)

        _options = [str(i) for i in range(0, 211, 15)]
        rs = RadioSettingValueList(
            _options, current_index=_settings.tot)
        rset = RadioSetting("settings.tot",
                            "TOT (s)", rs)
        settings.append(rset)

        _options = [str(i) for i in range(0, 10+1)]
        rs = RadioSettingValueList(
            _options, current_index=_settings.tot_alert)
        rset = RadioSetting("settings.tot_alert",
                            "TOT Alert (s)", rs)
        settings.append(rset)

        _opmap = [("Off", 0), ("55Hz", 1), ("120deg", 2),
                  ("180deg", 3), ("240deg", 4)]
        rs = RadioSettingValueMap(_opmap, _settings.tail_mode)
        rset = RadioSetting("settings.tail_mode", "Tail Mode", rs)
        settings.append(rset)

        exsettings = RadioSettingSubGroup("exsettings",
                                          "Extra Settings")
        settings.append(exsettings)

        _options = ['1000Hz', '1450Hz', '1750Hz', '2100Hz']
        rs = RadioSettingValueList(
            _options, current_index=_settings.hz1750)
        rset = RadioSetting("settings.hz1750",
                            "1750Hz", rs)
        exsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.eng_mode, mem_vals=(0, 1))
        rset = RadioSetting("settings.eng_mode", "Engineering Mode", rs)
        exsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.falling_alarm, mem_vals=(0, 1))
        rset = RadioSetting("settings.falling_alarm", "Falling Alarm", rs)
        exsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.alone_worker, mem_vals=(0, 1))
        rset = RadioSetting("settings.alone_worker", "Alone Worker", rs)
        exsettings.append(rset)

        rs = RadioSettingValueBoolean(
            current=_settings.enhance_func, mem_vals=(0, 1))
        rset = RadioSetting("settings.enhance_func", "Enhance Function", rs)
        exsettings.append(rset)

        _options = ['STAN', 'Fail']
        rs = RadioSettingValueList(
            _options, current_index=_settings.disp_reverse)
        rset = RadioSetting("settings.disp_reverse",
                            "Display Reverse", rs)
        exsettings.append(rset)

        _options = ['English', 'Chinese']
        rs = RadioSettingValueList(_options, current_index=_settings.language)
        rset = RadioSetting("settings.language",
                            "Language", rs)
        exsettings.append(rset)

        _current = _settings.lone_wrk_remind
        rs = RadioSettingValueInteger(minval=0, maxval=255,
                                      current=_current, step=1)
        rset = RadioSetting("settings.lone_wrk_remind",
                            "Lone Worker Remind (s)", rs)
        exsettings.append(rset)

        _current = _settings.lone_wrk_resp
        rs = RadioSettingValueInteger(minval=0, maxval=255,
                                      current=_current, step=1)
        rset = RadioSetting("settings.lone_wrk_resp",
                            "Lone Worker Response (min)", rs)
        exsettings.append(rset)

        # SCAN SETTINGS
        scanmenu = RadioSettingGroup("scanmenu", "Scan Settings")
        group.append(scanmenu)

        def apply_freq(setting, mem_setting):
            new_value = int(setting.values()[0]) * 10
            mem_setting.set_value(new_value)

        _current = int(_scan_freq.upper_freq)
        rs = RadioSettingValueInteger(minval=1360, maxval=4700,
                                      current=_current)
        rset = RadioSetting("scan_freq.lower_freq", "Scan Lower (KHz)", rs)
        rset.set_apply_callback(apply_freq, _scan_freq.lower_freq)
        scanmenu.append(rset)
        _current = int(_scan_freq.upper_freq)
        rs = RadioSettingValueInteger(minval=1360, maxval=4700,
                                      current=_current)
        rset = RadioSetting("scan_freq.upper_freq", "Scan Upper (KHz)", rs)
        rset.set_apply_callback(apply_freq, _scan_freq.upper_freq)
        scanmenu.append(rset)

        _options = ['TO', 'CO', 'SO']
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.scan_mode)
        rset = RadioSetting("scan_menu.scan_mode", "Scan Mode", rs)
        scanmenu.append(rset)

        a = [str(i/10) for i in range(5, 50+1, 1)]
        b = list(range(5, 50+1))
        _opmap = list(zip(a, b))
        rs = RadioSettingValueMap(_opmap, _scan_menu.flyback)
        rset = RadioSetting("scan_menu.flyback", "Flyback Time", rs)
        scanmenu.append(rset)

        a = [str(i/10) for i in range(1, 50+1, 1)]
        b = list(range(1, 50+1))
        _opmap = list(zip(a, b))
        rs = RadioSettingValueMap(_opmap, _scan_menu.rx_recovery)
        rset = RadioSetting("scan_menu.rx_recovery",
                            "RX Recovery Delay (s)", rs)
        scanmenu.append(rset)

        rs = RadioSettingValueMap(_opmap, _scan_menu.tx_recovery)
        rset = RadioSetting("scan_menu.tx_recovery",
                            "TX Recovery Delay (s)", rs)
        scanmenu.append(rset)

        _options = ['selected', 'selected + current', 'last call received',
                    'last use ', 'priority', 'priority + current']
        rs = RadioSettingValueList(
            _options, current_index=_scan_menu.channel_rtn)
        rset = RadioSetting("scan_menu.channel_rtn", "Channel Return", rs)
        scanmenu.append(rset)

        rs = RadioSettingValueBoolean(
            current=_scan_menu.priority, mem_vals=(0, 1))
        rset = RadioSetting("scan_menu.priority", "Priority", rs)
        scanmenu.append(rset)

        a = [str(i) for i in range(1, 64+1)]
        b = list(range(64))
        _opmap = list(zip(a, b))
        _current = _idx_or_default(_scan_menu.prio_scan_chan, b, 0)
        rs = RadioSettingValueMap(_opmap, _current)
        rset = RadioSetting("scan_menu.prio_scan_chan",
                            "Priority Scan Channel", rs)
        scanmenu.append(rset)

        _options = ['All', 'Memory Scan']
        rs = RadioSettingValueList(_options,
                                   current_index=_scan_menu.scan_range)
        rset = RadioSetting("scan_menu.scan_range", "Scan Range", rs)
        scanmenu.append(rset)

        # PROG KEY SETTINGS
        progkey = RadioSettingGroup("progkey", "Program Key")
        group.append(progkey)

        _opmap = [("None", 0), ("Scan On/Off", 1), ("Monitor", 2),
                  ("FM Radio", 4), ("Emergency", 5), ("GPS", 6),
                  ("Freq. Measuring", 7), ("1750Hz", 9),
                  ("Falling Alarm", 10), ("One Touch Call", 11),
                  ("Zone Change", 12), ("Battery Indicator", 13),
                  ("Tx Power", 14), ("VOX On/Off", 15)]

        rs = RadioSettingValueMap(
            _opmap, _prog_key.pf1_short)
        rset = RadioSetting("prog_key.pf1_short", "PF1 Short", rs)
        progkey.append(rset)

        rs = RadioSettingValueMap(
            _opmap, _prog_key.pf1_long)
        rset = RadioSetting("prog_key.pf1_long", "PF1 Long", rs)
        progkey.append(rset)

        rs = RadioSettingValueMap(
            _opmap, _prog_key.pf2_short)
        rset = RadioSetting("prog_key.pf2_short", "PF2 Short", rs)
        progkey.append(rset)

        rs = RadioSettingValueMap(
            _opmap, _prog_key.pf2_long)
        rset = RadioSetting("prog_key.pf2_long", "PF2 Long", rs)
        progkey.append(rset)

        dtmf = RadioSettingGroup("dtmf", "DTMF Settings")
        group.append(dtmf)

        rs = RadioSettingValueBoolean(
            current=_dtmf.dtmf_ani, mem_vals=(0, 1))
        rset = RadioSetting("dtmf.dtmf_ani", "DTMF ANI", rs)
        dtmf.append(rset)

        _options = ['50', '100', '200', '300', '500']
        rs = RadioSettingValueList(
            _options, current_index=_dtmf.sending_rate)
        rset = RadioSetting("dtmf.sending_rate", "Sending Rate (ms)", rs)
        dtmf.append(rset)

        _options = [str(i) for i in range(0, 2501, 10)]
        rs = RadioSettingValueList(
            _options, current_index=_dtmf.first_tm_code)
        rset = RadioSetting("dtmf.first_tm_code", "First Time Code (ms)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueList(
            _options, current_index=_dtmf.precarrier_tm)
        rset = RadioSetting("dtmf.precarrier_tm", "Precarrier Time (ms)", rs)
        dtmf.append(rset)

        a = [str(i) for i in range(10, 2501, 10)]
        b = list(range(1, 250+1))
        _opmap = list(zip(a, b))
        rs = RadioSettingValueMap(
            _opmap, _dtmf.delay_tm)
        rset = RadioSetting("dtmf.delay_tm", "Delay Time(ms)", rs)
        dtmf.append(rset)

        _options = [str(i) for i in range(0, 76, 5)]
        rs = RadioSettingValueList(
            _options, current_index=_dtmf.ptt_pause_tm)
        rset = RadioSetting("dtmf.ptt_pause_tm", "PTT Pause Time (s)", rs)
        dtmf.append(rset)

        rs = RadioSettingValueBoolean(current=_dtmf.dtmf_st, mem_vals=(0, 1))
        rset = RadioSetting("dtmf.dtmf_st", "DTMF-ST", rs)
        dtmf.append(rset)

        rs = RadioSettingValueInteger(minval=10, maxval=25,
                                      current=_dtmf.auto_reset_tm, step=1)
        rset = RadioSetting("dtmf.auto_reset_tm", "Auto Reset Time (s)", rs)
        dtmf.append(rset)

        _opmap = [("A", 0xa), ("B", 0xb), ("C", 0xc),
                  ("D", 0xd), ("*", 0xe), ("#", 0xf)]
        rs = RadioSettingValueMap(_opmap, _dtmf.sepr_opts)
        rset = RadioSetting("dtmf.sepr_opts", "Separator Option", rs)
        dtmf.append(rset)

        rs = RadioSettingValueMap(_opmap, _dtmf.group_num)
        rset = RadioSetting("dtmf.group_num", "Group Option", rs)
        dtmf.append(rset)

        _options = ['None', 'Tone', 'Tone Reply']
        rs = RadioSettingValueList(
            _options, current_index=_dtmf.decode_resp)
        rset = RadioSetting("dtmf.decode_resp", "Decode Response", rs)
        dtmf.append(rset)

        _current = "".join(str(int(c)) for c in _dtmf.self_id)
        rs = RadioSettingValueString(minlength=3, maxlength=3,
                                     current=_current,
                                     charset=[str(i) for i in range(10)],
                                     autopad=False)
        rset = RadioSetting("dtmf.self_id",
                            "Self ID", rs)
        dtmf.append(rset)

        def dtmf_xlate(setting):
            """ Translates * and # to ascii code E / F respectively"""
            s = ""
            for i in setting:
                if chr(i) == 'E':
                    s += '*'
                elif chr(i) == 'F':
                    s += '#'
                elif chr(i) in self.VALID_DTMF:
                    s += chr(i)
            return s

        _current = dtmf_xlate(_dtmf.ptt_id)
        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=_current,
                                     charset=self.VALID_DTMF)
        rset = RadioSetting("dtmf.ptt_id", "PTT ID Online", rs)
        dtmf.append(rset)

        _current = dtmf_xlate(_dtmf.ptt_id_offline)
        rs = RadioSettingValueString(minlength=0, maxlength=16,
                                     current=_current,
                                     charset=self.VALID_DTMF)
        rset = RadioSetting("dtmf.ptt_id_offline", "PTT ID Offine", rs)
        dtmf.append(rset)

        _current = dtmf_xlate(_dtmf.stun)
        rs = RadioSettingValueString(minlength=0, maxlength=11,
                                     current=_current,
                                     charset=self.VALID_DTMF)
        rset = RadioSetting("dtmf.stun", "STUN", rs)
        dtmf.append(rset)

        _current = dtmf_xlate(_dtmf.kill)
        rs = RadioSettingValueString(minlength=0, maxlength=11,
                                     current=_current,
                                     charset=self.VALID_DTMF)
        rset = RadioSetting("dtmf.kill", "KILL", rs)
        dtmf.append(rset)

        # DTMF Encode List
        dtmf_mem = RadioSettingGroup("dtmf_mem", "DTMF Encode List")
        group.append(dtmf_mem)

        for i in range(0, 16):  # 1-16
            rs = RadioSettingValueString(minlength=0, maxlength=16,
                                         current=dtmf_xlate(
                                             _dtmf_list[i].entry),
                                         charset=self.VALID_DTMF)
            rset = RadioSetting(f"dtmf_list[{i}].entry", f"Entry{i+1}", rs)
            dtmf_mem.append(rset)

        # APRS MENU
        aprs = RadioSettingGroup("aprs", "APRS Settings")
        group.append(aprs)

        _current = "".join(str(c) for c in _aprs_menu.selfid if str(
            c) in chirp_common.CHARSET_ALPHANUMERIC)
        rs = RadioSettingValueString(minlength=0, maxlength=6,
                                     current=_current,
                                     charset=chirp_common.CHARSET_ALPHANUMERIC)
        rset = RadioSetting("aprs_menu.selfid", "Self ID", rs)
        aprs.append(rset)

        _current = "".join(str(c) for c in _aprs_menu.targetid if str(
            c) in chirp_common.CHARSET_ALPHANUMERIC)
        rs = RadioSettingValueString(minlength=0, maxlength=6,
                                     current=_current,
                                     charset=chirp_common.CHARSET_ALPHANUMERIC)
        rset = RadioSetting("aprs_menu.targetid", "Target ID", rs)
        aprs.append(rset)

        _options = [str(i*-1) for i in range(16)]
        _idx = _idx_or_default(_aprs_menu.self_ssid, _current, 0)
        rs = RadioSettingValueList(
            _options, current_index=_idx)
        rset = RadioSetting("aprs_menu.self_ssid", "Self SSID", rs)
        aprs.append(rset)

        _idx = _idx_or_default(_aprs_menu.target_ssid, _current, 0)
        rs = RadioSettingValueList(
            _options, current_index=_idx)
        rset = RadioSetting("aprs_menu.target_ssid", "Target SSID", rs)
        aprs.append(rset)

        _options = [str(i) for i in range(0, 2551, 10)]
        rs = RadioSettingValueList(
            _options, current_index=_aprs_menu.precarrier_tm)
        rset = RadioSetting("aprs_menu.precarrier_tm",
                            "Precarrier Time (ms)", rs)
        aprs.append(rset)

        rs = RadioSettingValueList(
            _options, current_index=_aprs_menu.code_dly_tm)
        rset = RadioSetting("aprs_menu.code_dly_tm",
                            "Code Delay Time (ms)", rs)
        aprs.append(rset)

        # APRS SSID List
        ssid = RadioSettingGroup("ssid", "APRS List")
        group.append(ssid)
        for i in range(0, 8):  # 1-8
            rs = RadioSettingValueMap(self.SSID_OPMAP, _ssid_tbl[i].ssid)
            rset = RadioSetting(f"ssid_tbl[{i}].ssid", f"{i+1}: SSID", rs)
            ssid.append(rset)
            _charset = chirp_common.CHARSET_ALPHANUMERIC
            _current = "".join(str(c) for c in _ssid_tbl[i].entry if str(
                c) in chirp_common.CHARSET_ALPHANUMERIC)
            rs = RadioSettingValueString(minlength=0, maxlength=6,
                                         current=_current,
                                         charset=_charset)
            rset = RadioSetting(f"ssid_tbl[{i}].entry", "Call Sign", rs)
            ssid.append(rset)

        # Contacts List
        contacts = RadioSettingGroup("contacts", "Contacts List")
        group.append(contacts)

        for i in range(0, 80):  # 1-80
            rs = RadioSettingValueInteger(minval=0, maxval=255,
                                          current=_contacts[i].code)
            rset = RadioSetting(f"contacts[{i}].code", f"{i+1}:", rs)
            contacts.append(rset)
            _charset = self.VALID_CHARSET
            _current = "".join(
                str(c) for c in _contacts[i].name if str(c) in _charset)
            rs = RadioSettingValueString(minlength=0, maxlength=14,
                                         current=_current,
                                         charset=_charset)
            rset = RadioSetting(f"contacts[{i}].name", "Name", rs)
            contacts.append(rset)

        return group

    def _dtmf_set__mem(self, obj, setting, element):
        _dtmf_map = [str(i) for i in range(10)]
        _dtmf_map += ['A', 'B', 'C', 'D', '*', '#']
        _val = [0xff] * len(obj[setting])
        _os = 0  # offset _mem setting idx for pad chars
        for i in range(len(element.value)):
            if element.value[i] in _dtmf_map:
                _val[i - _os] = _dtmf_map.index(element.value[i])
            else:
                _os += 1
        setattr(obj, setting, _val)

    def _ssid_set__mem(self, obj, setting, element):
        _ssid_map = list(chirp_common.CHARSET_ALPHANUMERIC)
        _ssid_map.remove(' ')
        _val = [0] * len(obj[setting])
        _os = 0  # offset _mem setting idx for pad chars
        for i in range(len(element.value)):
            if element.value[i] in _ssid_map:
                _val[i - _os] = _ssid_map.index(element.value[i])
            else:
                _os += 1
        setattr(obj, setting, _val)

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        toks = element.get_name().split(".")
                        obj = self._memobj
                        for tok in toks[:-1]:
                            if '[' in tok:
                                t, i = tok.split("[")
                                i = int(i[:-1])
                                obj = getattr(obj, t)[i]
                            else:
                                obj = getattr(obj, tok)
                        setting = toks[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("applying callback")
                        element.run_apply_callback()

                    if element.value.get_mutable():
                        if setting in ['ptt_id', 'ptt_id_offline',
                                       'stun', 'kill']:
                            self._dtmf_set__mem(obj, setting, element)
                        elif obj._name in ['ssid_tbl', 'dtmf_list']:
                            if obj._name == 'ssid_tbl':
                                if setting == 'entry':
                                    self._ssid_set__mem(obj, setting, element)
                                elif setting == 'ssid':
                                    print(element.value)
                                    _value = 255 if element.value == 'None' else \
                                        abs(int(element.value))
                                    setattr(obj, setting, _value)
                                else:
                                    setattr(obj, setting, element.value)
                            elif obj._name == 'dtmf_list':
                                if setting == 'entry':
                                    self._dtmf_set__mem(obj, setting, element)
                                else:
                                    setattr(obj, setting, element.value)
                        else:
                            setattr(obj, setting, element.value)
                except Exception:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        # new drivers identified by metadata
        return False


# Loaded from issue 11669 attachment 13201: https://chirpmyradio.com/attachments/download/13201/baofeng_bf5rhPro.py
