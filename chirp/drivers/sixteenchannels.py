# template.py: Copyright 2012 Dan Smith <dsmith@danplanet.com>
# boblov_x3plus.py: Copyright 2018 Robert C Jennings <rcj4747@gmail.com>
# h777.py: Copyright 2013 Andrew Morgan <ziltro@ziltro.com>
# kyd.py: Copyright 2014 Jim Unroe <rock.unroe@gmail.com>
# kyd.py: Copyright 2014 Dan Smith <dsmith@danplanet.com>
# radioddity_r2.py: Copyright August 2018 Klaus Ruebsam <dg5eau@ruebsam.eu>
# radtel_t18.py: Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
# retevis_h777v4.py: Copyright 2025 Jim Unroe <rock.unroe@gmail.com>
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

import logging
import struct
import time
import unittest

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    kenwood_tone,
    memmap,
    util,
)

from chirp.settings import (
    InvalidValueError,
    MemSetting,
    RadioSetting,
    RadioSettingGroup,
    RadioSettingSubGroup,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueInvertedBoolean,
    RadioSettingValueList,
    RadioSettingValueMap,
    RadioSettingValueString,
    RadioSettings,
)

LOG = logging.getLogger(__name__)

MEMORY = """
#seekto 0x0010;
struct {
    lbcd rxfreq[4];     // 0-3
    lbcd txfreq[4];     // 4-7
    ul16 rxtone;        // 8-9
    ul16 txtone;        // A-B
    u8  speccode:1,     // Spec Code:   0 = On, 1 = Off (Retevis RB87 PTT ID)
        compander:1,    // Compander:   0 = On, 1 = Off
        scramble:1,     // Scramble:    0 = Off, 1 = On
        skip:1,         // Scan Add:    0 = Scan, 1 = Skip
        highpower:1,    // Power Level: 0 = Low, 1 = High
        narrow:1,       // Bandwidth:   0 = Wide, 1 = Narrow
        beatshift:1,    //
        bcl:1;          // Busy Channel Lockout: 0 = On, 1 = Off
    u8  unknown[3];
// the last three bytes of every channel are identical
// to the first three bytes of the next channel in row.
// However, it will automatically be filled by the radio itself.
} memory[16];
"""

X02B0_SETTINGS = """
#seekto 0x02B0;
struct {
    u8 voiceprompt;         // Voice Prompt 0=Off, 1=Chinese, 2=English
    u8 voicelanguage;       // Voice Language 0=Chinese, 1=English
    u8 scan;                // Scan 0=Off, 1=On
    u8 vox;                 // VOX 0=Off, 1=On
    u8 voxlevel;            // VOX Level
    u8 voxinhibitonrx;      // VOX Inhibit on RX 0=Off, 1=On
    u8 lowvolinhibittx;     // Low Voltage TX Inhibit 0=Off, 1=On
    u8 highvolinhibittx;    // High Voltage TX Inhibit 0=Off, 1=On
    u8 alarm;               // Alarm 0=Off, 1=On
    u8 fmradio;             // FM Radio 0=Off, 1=On
} x02B0_settings;
"""

X03C0_SETTINGS = """
#seekto 0x03C0;
struct {
    u8 codesw:1,         // Retevis RB29 code switch
                         // Retevis H777H code switch
       scanmode:1,
       vox:1,            // Retevis RB19 VOX
       speccode:1,       // Retevis H777H VOX
       voiceprompt:2,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 sidekeyfunction;  // Retevis RT22S setting
                         // Retevis RB85 sidekey 1 short
                         // Retevis RB19 sidekey 2 long
                         // Retevis RT47 sidekey 1 long
                         // Retevis RB87 sidekey 1 long
                         // Retevis H777H roger
    u8 timeouttimer;
    u8 voxgain;
    u8 specialcode;
    u8 unknown3c6;
    u8 unused3:7,
       scanmode:1;
} x03C0_settings;
"""

BF1900_X03C0_SETTINGS = """
#seekto 0x03C0;
struct {
    u8 unused:6,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 scanmode;
    u8 timeouttimer;
    u8 unused2[4];
} bf1900_x03C0_settings;
"""

CMD_ACK = b'\x06'
CMD_ALT_ACK = b'\x53'
CMD_STX = b'\x02'
CMD_ENQ = b'\x05'
BLOCK_SIZE = 0x08
UPLOAD_BLOCKS = [
    list(range(0x0000, 0x0110, 8)),
    list(range(0x02B0, 0x02C0, 8)),
    list(range(0x0380, 0x03E0, 8)),
]

VOICE_LIST1 = ['Off', 'Chinese', 'English']
VOICE_LIST2 = ['Chinese', 'English']
VOICE_LIST3 = ['Off', 'English', 'Chinese']
VOICE_LIST4 = ['English', 'Chinese']
TIMEOUTTIMER_LIST = [
    'Off',
    '30 seconds',
    '60 seconds',
    '90 seconds',
    '120 seconds',
    '150 seconds',
    '180 seconds',
    '210 seconds',
    '240 seconds',
    '270 seconds',
    '300 seconds',
]

FRS16_FREQS = [
    462562500,
    462587500,
    462612500,
    462637500,
    462662500,
    462625000,
    462725000,
    462687500,
    462712500,
    462550000,
    462575000,
    462600000,
    462650000,
    462675000,
    462700000,
    462725000,
]

FRS_FREQS1 = [
    462562500,
    462587500,
    462612500,
    462637500,
    462662500,
    462687500,
    462712500,
]
FRS_FREQS2 = [
    467562500,
    467587500,
    467612500,
    467637500,
    467662500,
    467687500,
    467712500,
]
FRS_FREQS3 = [
    462550000,
    462575000,
    462600000,
    462625000,
    462650000,
    462675000,
    462700000,
    462725000,
]
FRS_FREQS = FRS_FREQS1 + FRS_FREQS2 + FRS_FREQS3

GMRS_FREQS = FRS_FREQS1 + FRS_FREQS2 + FRS_FREQS3 * 2

MURS_FREQS = [151820000, 151880000, 151940000, 154570000, 154600000]

PMR_FREQS1 = [
    446006250,
    446018750,
    446031250,
    446043750,
    446056250,
    446068750,
    446081250,
    446093750,
]
PMR_FREQS2 = [
    446106250,
    446118750,
    446131250,
    446143750,
    446156250,
    446168750,
    446181250,
    446193750,
]
PMR_FREQS = PMR_FREQS1 + PMR_FREQS2

PMR_TONES = (
    0.0,
    67.0,
    71.9,
    74.4,
    77.0,
    79.7,
    82.5,
    85.4,
    88.5,
    91.5,
    94.8,  # 10
    97.4,
    100.0,
    103.5,
    107.2,
    110.9,
    114.8,
    118.8,
    123.0,
    127.3,
    131.8,  # 20
    136.5,
    141.3,
    146.2,
    151.4,
    156.7,
    162.2,
    167.9,
    173.8,
    179.9,
    186.2,  # 30
    192.8,
    203.5,
    210.7,
    218.1,
    225.7,
    233.6,
    241.8,
    250.3,  # 38
)

PMR_DCS_CODES = (
    23,  # 39
    25,  # 40
    26,
    31,
    32,
    43,
    47,
    51,
    54,
    65,
    71,
    72,  # 50
    73,
    74,
    114,
    115,
    116,
    125,
    131,
    132,
    134,
    143,  # 60
    152,
    155,
    156,
    162,
    165,
    172,
    174,
    205,
    223,
    226,  # 70
    243,
    244,
    245,
    251,
    261,
    263,
    265,
    271,
    306,
    311,  # 80
    315,
    331,
    343,
    346,
    351,
    364,
    365,
    371,
    411,
    412,  # 90
    413,
    423,
    431,
    432,
    445,
    464,
    465,
    466,
    503,
    506,  # 100
    516,
    532,
    546,
    565,
    606,
    612,
    624,
    627,
    631,
    632,  # 110
    654,
    662,
    664,
    703,
    712,
    723,
    731,
    732,
    734,
    743,  # 120
    754,  # 121
)

PMR_CODES = PMR_TONES + PMR_DCS_CODES

TONES = chirp_common.TONES
DTCS_CODES = chirp_common.DTCS_CODES


def _enter_programming_mode(radio):
    _serial = radio.pipe

    _magic = CMD_STX + radio._magic

    try:
        _serial.write(_magic)
        if radio._echo:
            _serial.read(len(_magic))  # Chew the echo
        ack = _serial.read(1)
    except Exception as exc:
        LOG.exception('Failed to enter programming mode.')
        raise errors.RadioError("Error communicating with radio")

    if not ack:
        raise errors.RadioNoResponse()
    elif ack != CMD_ACK:
        LOG.warning('Ack from program command was %r, expected %r',
                    ack, CMD_ACK)
        raise errors.RadioError("Radio refused to enter programming mode")

    try:
        _serial.write(CMD_STX)
        # At least one version of the Baofeng BF-888S has a consistent
        # ~0.33s delay between sending the first five bytes of the
        # version data and the last three bytes. We need to raise the
        # timeout so that the read doesn't finish early.
        if radio._echo:
            _serial.read(1)  # Chew the echo
        ident = _serial.read(8)
    except Exception as exc:
        LOG.exception('Failed to read ident')
        raise errors.RadioError("Error communicating with radio")

    if ident:
        LOG.info('Radio identified with:\n%s', util.hexprint(ident))
        # check if ident is OK
        for fp in radio._fingerprint:
            if ident.startswith(fp):
                break
        else:
            LOG.debug('Incorrect model ID, got this: ' + util.hexprint(ident))
            raise errors.RadioError('Radio identification failed.')

        try:
            _serial.write(CMD_ACK)
            if radio._echo:
                _serial.read(1)  # Chew the echo
            ack = _serial.read(1)

            if radio.MODEL == 'RT647':
                if ack != b'\xf0':
                    raise errors.RadioError('Bad ACK after reading ident')
            else:
                if ack != CMD_ACK:
                    LOG.warning('Bad ACK after reading ident')
                    raise errors.RadioError('Bad ACK after reading ident')
        except Exception as exc:
            LOG.exception('No ACK after reading ident')
            raise errors.RadioError(f'No ACK after reading ident: {exc}')
        return ident

    raise errors.RadioNoResponse()


def _exit_programming_mode(radio):
    LOG.debug('Begin _exit_programming_mode')
    serial = radio.pipe
    try:
        serial.write(radio.CMD_EXIT)
        if radio._echo:
            serial.read(1)  # Chew the echo
    except Exception as exc:
        LOG.exception('Failed to send exit command')
        raise errors.RadioError(
            f'Radio refused to exit programming mode: {exc}'
        )
    LOG.debug('End _exit_programming_mode')


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack('>cHb', b'R', block_addr, block_size)
    expectedresponse = b'W' + cmd[1:]
    LOG.debug(f'Reading {block_size:04x} byte block at {block_addr:04x}...')

    try:
        serial.write(cmd)
        if radio._echo:
            serial.read(4)  # Chew the echo
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            LOG.warning(
                'Got %r; Expected %r' % (response[:4], expectedresponse)
            )
            raise Exception(
                'Error reading %04x byte block at %04x.',
                block_size,
                block_addr,
            )

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except Exception as exc:
        LOG.exception(
            'Failed to read %04x byte block at %04x.',
            block_size,
            block_addr,
        )
        raise errors.RadioError(
            f'Failed to read {block_size:04x} byte block at {block_addr:04x}: {exc}'
        )

    if ack != CMD_ACK:
        raise errors.RadioError(
            f'No ACK reading {block_size:04x} byte block at {block_addr:04x}.'
        )

    return block_data


def _h777_write_block(radio, block_addr):
    serial = radio.pipe

    cmd = struct.pack('>cHb', b'W', block_addr, BLOCK_SIZE)
    data = radio.get_mmap().get_byte_compatible()[block_addr : block_addr + 8]

    radio.pipe.log('Writing %i block at %04x' % (BLOCK_SIZE, block_addr))

    try:
        serial.write(cmd + data)
        # Time required to write data blocks varies between individual
        # radios of the Baofeng BF-888S model. The longest seen is
        # ~0.31s.
        if serial.read(1) != CMD_ACK:
            raise Exception('No ACK')
    except Exception as exc:
        LOG.exception('Failed to send block at %04x' % block_addr)
        raise errors.RadioError(
            f'Failed to send block at {block_addr:04x}: {exc}'
        )


def _download(radio):
    "Initiate a radio-to-PC clone operation"

    data = b''

    LOG.debug('Cloning from radio')
    status = chirp_common.Status()
    status.msg = 'Cloning from radio'
    status.cur = 0
    status.max = radio._memsize
    radio.status_fn(status)

    radio._enter_programming_mode()

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        block = radio._read_block(addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug('Address: %04x', addr)
        LOG.debug(util.hexprint(block))

    radio._exit_programming_mode()

    return memmap.MemoryMapBytes(data)


def _upload(radio):
    "Initiate a PC-to-radio clone operation"

    LOG.debug('Uploading to radio')
    status = chirp_common.Status()
    status.msg = 'Uploading to radio'
    status.cur = 0
    status.max = radio._memsize
    radio.status_fn(status)

    radio._enter_programming_mode()

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE):
            status.cur = addr + radio.BLOCK_SIZE
            radio.status_fn(status)
            radio._write_block(addr, radio.BLOCK_SIZE)

    radio._exit_programming_mode()


# Uncomment this to actually register this radio in CHIRP
# @directory.register
class SixteenChannelRadio(
    chirp_common.CloneModeRadio, chirp_common.ExperimentalRadio
):
    """A base class for common 16-channel radios."""

    VENDOR = 'Acme'  # Replace this with your vendor
    MODEL = 'Template'  # Replace this with your model
    BAUD_RATE = 9600  # Replace this with your baud rate
    NEEDS_COMPAT_SERIAL = True
    CHANNELS = 16
    MEMORY_FORMAT = []
    ALARM_LIST = []
    _tone_model = kenwood_tone.KenwoodToneModel(
        dcs_base=0x8000,
        pol_mask=0x4000,
        tone_init=0xFFFF,
        tone_flag=0x0000,
        dcs_enc_base=16,
        tone_enc_base=16,
    )

    # General
    _has_bank_index = False
    _has_dtcs = True
    _has_rx_dtcs = True
    _has_dtcs_polarity = True
    _has_mode = True
    _has_offset = True
    _has_name = False
    _has_bank = False
    _has_bank_names = False
    _has_tuning_step = False
    _has_ctone = True
    _has_cross = True
    _has_infinite_number = False
    _has_nostep_tuning = False
    _has_comment = False
    _has_settings = True
    _has_variable_power = True
    _has_dynamic_subdevices = False

    _has_sub_devices = False
    _memory_bounds = (1, 16)
    _can_odd_split = True
    _can_delete = False

    _memsize = 0x03E0
    _has_fm = True
    _has_sidekey = True
    _has_scanmodes = True
    _has_scramble = True
    _upper = 16
    _mem_params = _upper  # number of channels
    _frs = _frs16 = _murs = _pmr = _gmrs = False
    _echo = False
    _reserved = False

    # All new drivers should be "Byte Clean" so leave this in place.

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        """
        Override from chirp_common.Radio.
        Return a RadioFeatures object for this radio.
        """
        rf = chirp_common.RadioFeatures()
        # General
        rf.has_bank_index = self._has_bank_index
        rf.has_dtcs = self._has_dtcs
        rf.has_rx_dtcs = self._has_rx_dtcs
        rf.has_dtcs_polarity = self._has_dtcs_polarity
        rf.has_mode = self._has_mode
        rf.has_offset = self._has_offset
        rf.has_name = self._has_name
        rf.has_bank = self._has_bank
        rf.has_bank_names = self._has_bank_names
        rf.has_tuning_step = self._has_tuning_step
        rf.has_ctone = self._has_ctone
        rf.has_cross = self._has_cross
        rf.has_infinite_number = self._has_infinite_number
        rf.has_nostep_tuning = self._has_nostep_tuning
        rf.has_comment = self._has_comment
        rf.has_settings = self._has_settings
        rf.has_variable_power = self._has_variable_power
        rf.has_dynamic_subdevices = self._has_dynamic_subdevices

        # Attributes
        rf.valid_modes = self.MODES
        rf.valid_tmodes = self.TMODES
        rf.valid_duplexes = self.DUPLEX
        rf.valid_tuning_steps = self.STEPS
        rf.valid_bands = self.BANDS
        rf.valid_skips = self.SKIPS
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_characters = self.CHARSET
        rf.valid_name_length = self.NAME_LENGTH
        rf.valid_cross_modes = self.CROSS_MODES
        rf.valid_tones = self.TONES
        rf.valid_dtcs_pols = self.POLS
        rf.valid_dtcs_codes = self.DTCS_CODES
        rf.valid_special_chans = []

        rf.has_sub_devices = False
        rf.memory_bounds = (1, 16)
        rf.can_odd_split = True
        rf.can_delete = True

        return rf

    def get_prompts(self):
        """Override from chirp_common.Radio"""
        pass

    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):
        """
        Override from chirp_common.Radio
        Return a Memory object for the memory at location @number
        """
        # Arrays are zero-indexed, so channel 1 goes in index 0
        _index = int(number) - 1
        try:
            # Get a low-level memory object mapped to the image
            _mem = self._memobj.memory[_index]
        except KeyError as ke:
            raise errors.InvalidMemoryLocation(
                f'Unknown channel {number}'
            ) from ke

        if _index < 0 or _index >= self.CHANNELS:
            raise errors.InvalidMemoryLocation(
                f'Channel number must be between 1 and {self.CHANNELS}'
            )

        # Create a high-level memory object to return to the UI
        mem = chirp_common.Memory()

        mem.number = int(number)  # Set the memory number
        # Convert your low-level frequency to Hertz
        mem.freq = int(_mem.freq)
        mem.name = str(_mem.name).rstrip()  # Set the alpha tag

        # We'll consider any blank (i.e. 0 MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True

        return mem

    def get_memories(self, lo, hi):
        """Override from chirp_common.Radio"""
        pass

    # Store details about a high-level memory to the memory map
    # This is called when a user edits a memory in the UI
    def set_memory(self, mem):
        """Override from chirp_common.Radio"""
        # Arrays are zero-indexed, so channel 1 goes in index 0
        _index = int(mem.number) - 1
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[_index]

        # Convert to low-level frequency representation
        _mem.freq = mem.freq
        _mem.name = mem.name.ljust(8)[:8]  # Store the alpha tag

    # Return a raw representation of the memory object, which
    # is very helpful for development
    def get_raw_memory(self, number):
        """Override from chirp_common.Radio"""
        # Arrays are zero-indexed, so channel 1 goes in index 0
        return repr(self._memobj.memory[int(number) - 1])

    def get_settings(self):
        """Override from chirp_common.Radio"""
        pass

    def set_settings(self):
        """Override from chirp_common.Radio"""
        pass

    def save(self, filename):
        """
        Override from chirp_common.FileBackedRadio
        Overridden in chirp_common.CloneModeRadio
        """
        pass

    def load(self, filename):
        """
        Override from chirp_common.FileBackedRadio
        Overridden in chirp_common.CloneModeRadio
        """
        pass

    def detect_from_serial(self, pipe):
        """Override from chirp_common.DetectableInterface"""
        pass

    # Do a download of the radio from the serial port
    def sync_in(self):
        """
        Override from chirp_common.CloneModeRadio
        Initiate a radio-to-PC clone operation.
        """
        try:
            data = _download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except Exception as exc:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError(
                'Unexpected error communicating with the radio'
            ) from exc
        self._mmap = data
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        """
        Override from chirp_common.CloneModeRadio
        Initiate a PC-to-radio clone operation.
        """
        try:
            _upload(self)
        except errors.RadioError:
            raise
        except Exception as exc:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Failed to upload to radio') from exc

    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        """
        Override from chirp_common.CloneModeRadio
        Process a newly-loaded or downloaded memory map
        """
        self._memobj = bitwise.parse(self.MEMORY_FORMAT, self._mmap)


@directory.register
class BaofengBF888(SixteenChannelRadio):
    """Baofeng BF-888"""

    VENDOR = 'Baofeng'
    MODEL = 'BF-888'
    PROGRAM_CMD = b'PROGRAM'
    IDENT = [
        b'P3107',
    ]
    POWER_LEVELS = [
        chirp_common.PowerLevel('Low', watts=1.00),
        chirp_common.PowerLevel('High', watts=5.00),
    ]
    VALID_BANDS = (400000000, 490000000)
    MAX_VOXLEVEL = 5
    SIDEKEYFUNCTION_LIST = ['Off', 'Monitor', 'Transmit Power', 'Alarm']
    SCANMODE_LIST = ['Carrier', 'Time']


@directory.register
class RetevisH777(BaofengBF888):
    VENDOR = 'Retevis'
    MODEL = 'H777'
    ALIASES = []

    @classmethod
    def detect_from_serial(cls, pipe):
        cls_to_ident = {rc: rc.IDENT for rc in cls.detected_models()}
        for ident_rclass in reversed(cls.detected_models()):
            ident = _enter_programming_mode(self)
            for rclass, idents in cls_to_ident.items():
                if any(rc_ident in ident for rc_ident in idents):
                    LOG.debug('Detected %s', rclass.__name__)
                    return rclass
                LOG.debug('Ident was %r, idents were %r', ident, idents)

            LOG.info('Did not identify radio as %s', rclass.__name__)
            time.sleep(0.5)
            _exit_programming_mode(pipe)
            time.sleep(1)

        raise errors.RadioError('Failed to identify with radio.')


MP31_MEM_FORMAT = """
#seekto 0x0000;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    ul16 rxtone;
    ul16 txtone;
    u8 unknown3:1,
       unknown2:1,
       unknown1:1,
       skip:1,
       highpower:1,
       narrow:1,
       beatshift:1,
       bcl:1;
    u8 unknown4[3];
} memory[38];
"""

MP31_SETTINGS2 = """
#seekto 0x026B;
struct {
    u8 squelchlevel;
    u8 batterysaver;
    u8 voxdelay;
    u8 timeouttimer;
    u8 scanmode;
    u8 beep;
    u8 sidekey;
    u8 rxemergency;
} settings2;
"""


@directory.register
class BaofengMP31(BaofengBF888):
    """Baofeng MP31"""

    VENDOR = "Baofeng"
    MODEL = "MP31"
    IDENT = [b"P3107\xf7\x00\x00"]
    _ranges = [(0x0000, 0x0400)]
    _memsize = 0x0400
    _has_sidekey = False
    ALIASES = []

    def process_mmap(self):
        self._memobj = bitwise.parse(
            MP31_MEM_FORMAT + MP31_SETTINGS2 + MEM_FORMAT_SETTINGS, self._mmap)

    def get_features(self):
        rf = super().get_features()
        rf.memory_bounds = (1, 38)
        return rf

    @classmethod
    def match_model(cls, filedata, filename):
        return False


@directory.register
class RadioddityGA2S(BaofengBF888):
    VENDOR = "Radioddity"
    MODEL = "GA-2S"
    ALIASES = []
    _has_fm = False
    SIDEKEYFUNCTION_LIST = ["Off", "Monitor", "Unused", "Alarm"]

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class H777PlusRadio(BaofengBF888):
    VENDOR = "Retevis"
    MODEL = "H777 Plus"
    ALIASES = []
    _has_fm = False
    _has_scanmodes = False

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class BFM4Radio(BaofengBF888):
    VENDOR = "Baofeng"
    MODEL = "BF-M4"
    ALIASES = []
    _has_fm = False

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class MT8SRadio(BaofengBF888):
    VENDOR = "MaxTalker"
    MODEL = "MT-8S"
    ALIASES = []
    _has_fm = False

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class BaofengBF1901(BaofengBF888):
    VENDOR = "Baofeng"
    MODEL = "BF-1901"
    PROGRAM_CMD = b'PWPG970'
    ALIASES = []

    VALID_BANDS = (400000000, 520000000)
    MAX_VOXLEVEL = 9
    SCANMODE_LIST = ["Time", "Carrier", "Search"]
    ALARM_LIST = ["Local", "Remote"]

    _has_fm = True
    _has_sidekey = False
    _has_scanmodes = True
    _has_scramble = False

    def process_mmap(self):
        self._memobj = bitwise.parse(MEMORY + BF1900_X03C0_SETTINGS, self._mmap)

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class BaofengBF1904(BaofengBF1901):
    VENDOR = "Baofeng"
    MODEL = "BF-1904"
    ALIASES = []

    # TODO: Is it 1 watt?
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("High", watts=10.00)]

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class BaofengBF1909(BaofengBF1901):
    VENDOR = "Baofeng"
    MODEL = "BF-1909"
    ALIASES = []
    IDENT = [b"P320h",
             b"P3107" + b"\xF4" + b"AM",
             ]
    _ranges = [
        (0x0000, 0x0110),
        (0x0250, 0x0260),
        (0x02B0, 0x02C0),
        (0x03C0, 0x03E0),
    ]
    _memsize = 0x03F0

    # TODO: Is it 1 watt?
    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("High", watts=10.00)]

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class MAVERICKRA100Radio(BFM4Radio):
    VENDOR = "Maverick"
    MODEL = "RA-100"
    ALIASES = []

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class MAVERICKRA425Radio(BaofengBF1904):
    VENDOR = "Maverick"
    MODEL = "RA-425"
    ALIASES = []
    _has_fm = False

    @classmethod
    def match_model(cls, filedata, filename):
        # This model is only ever matched via metadata
        return False


@directory.register
class RadioddityR2(SixteenChannelRadio):
    """Radioddity R2"""

    VENDOR = 'Radioddity'
    MODEL = 'R2'

    # definitions on how to read StartAddr EndAddr BlockSize
    _ranges = [(0x0000, 0x01F8, 0x08), (0x01F8, 0x03F0, 0x08)]
    _memsize = 0x03F0
    # never read more than 8 bytes at once
    _block_size = 0x08
    # frequency range is 400-470 MHz
    _range = [400000000, 470000000]
    # maximum 16 channels
    _upper = 16
    _mem_params = {
        'memnum': _upper,  # number of channels
    }

    _frs16 = _pmr = False


@directory.register
class RetevisRT24(RadioddityR2):
    """Retevis RT24"""

    VENDOR = 'Retevis'
    MODEL = 'RT24'

    _pmr = False  # sold as PMR radio but supports full band TX/RX


@directory.register
class RetevisRT24V(RadioddityR2):
    """Retevis RT24V"""

    VENDOR = 'Retevis'
    MODEL = 'RT24V'

    # sold as FreeNet radio but supports full band TX/RX

    # frequency range is 136-174 MHz
    _range = [136000000, 174000000]
    # maximum 6 channels
    _upper = 6
    _mem_params = {
        'memnum': _upper,  # number of channels
    }


@directory.register
class RetevisH777S(RadioddityR2):
    """Retevis H777S"""

    VENDOR = 'Retevis'
    MODEL = 'H777S'

    _frs16 = False  # sold as FRS radio but supports full band TX/RX


@directory.register
class T18Radio(SixteenChannelRadio):
    """Radtel T18"""

    VENDOR = 'Radtel'
    MODEL = 'T18'
    BLOCK_SIZE = 0x08
    CMD_EXIT = b'b'
    _magic = b'1ROGRAM'
    _fingerprint = [b'SMP558' + b'\x00\x00']


@directory.register
class RT20Radio(T18Radio):
    """Retevis RT20"""

    VENDOR = 'Retevis'
    MODEL = 'RT20'
    ACK_BLOCK = True
    BLOCK_SIZE = 0x08

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'8AOGRAM'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 16
    _mem_params = _upper  # number of channels


@directory.register
class RT22SRadio(T18Radio):
    """Retevis RT22S"""

    VENDOR = 'Retevis'
    MODEL = 'RT22S'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'9COGRAM'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 22
    _mem_params = _upper  # number of channels
    _frs = True
    _pmr = False


MEM_FORMAT_RB18 = """
#seekto 0x0000;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    lbcd rxtone[2];
    lbcd txtone[2];
    u8 jumpcode:1,
       unknown1:2,
       skip:1,
       highpower:1,
       narrow:1,
       unknown2:1,
       bcl:1;
    u8 unknown3[3];
} memory[%d];
#seekto 0x0630;
struct {
    u8 unk630:7,
       voice:1;
    u8 unk631:7,
       language:1;
    u8 unk632:7,
       scan:1;
    u8 unk633:7,
       vox:1;
    u8 unk634:5,
       vox_level:3;
    u8 unk635;
    u8 unk636:7,
       lovoltnotx:1;
    u8 unk637:7,
       hivoltnotx:1;
    u8 unknown2[8];
    u8 unk640:5,
       rogerbeep:1,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 unk642;
    u8 timeouttimer;
    u8 unk644:7,
       tail:1;
    u8 channel;
} settings;
"""


@directory.register
class RB18Radio(T18Radio):
    """Retevis RB18"""

    VENDOR = 'Retevis'
    MODEL = 'RB18'
    BLOCK_SIZE = 0x10
    CMD_EXIT = b'E'

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'PROGRAL'
    _fingerprint = [b'P3107' + b'\xf7']
    _upper = 22
    _mem_params = _upper  # number of channels
    _frs = True
    _pmr = False

    _ranges = [
        (0x0000, 0x0660),
    ]
    _memsize = 0x0660

    def process_mmap(self):
        self._memobj = bitwise.parse(
            MEM_FORMAT_RB18 % self._mem_params, self._mmap
        )

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RB618Radio(RB18Radio):
    """Retevis RB618"""

    VENDOR = 'Retevis'
    MODEL = 'RB618'

    _upper = 16
    _mem_params = _upper  # number of channels
    _frs = False
    _pmr = True


@directory.register
class RT68Radio(T18Radio):
    """Retevis RT68"""

    VENDOR = 'Retevis'
    MODEL = 'RT68'
    ACK_BLOCK = False
    CMD_EXIT = b''

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'83OGRAM'
    _fingerprint = [b'\x06\x00\x00\x00\x00\x00\x00\x00']
    _upper = 16
    _mem_params = _upper  # number of channels
    _frs16 = True
    _pmr = False

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RT668Radio(RT68Radio):
    """Retevis RT668"""

    VENDOR = 'Retevis'
    MODEL = 'RT668'

    _frs16 = False
    _pmr = True


@directory.register
class RB17Radio(RT68Radio):
    """Retevis RB17"""

    VENDOR = 'Retevis'
    MODEL = 'RB17'

    _magic = b'A5OGRAM'
    _fingerprint = [b'\x53\x00\x00\x00\x00\x00\x00\x00']

    _frs16 = True
    _pmr = False
    _murs = False


@directory.register
class RB617Radio(RB17Radio):
    """Retevis RB617"""

    VENDOR = 'Retevis'
    MODEL = 'RB617'

    _frs16 = False
    _pmr = True
    _murs = False


@directory.register
class RB17VRadio(RB17Radio):
    """Retevis RB17V"""

    VENDOR = 'Retevis'
    MODEL = 'RB17V'

    VALID_BANDS = [(136000000, 174000000)]

    _upper = 5

    _frs16 = False
    _pmr = False
    _murs = True


@directory.register
class RB85Radio(T18Radio):
    """Retevis RB85"""

    VENDOR = 'Retevis'
    MODEL = 'RB85'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=10.00),
        chirp_common.PowerLevel('Low', watts=5.00),
    ]

    _magic = b'H19GRAM'
    _fingerprint = [b'SMP558' + b'\x02']


@directory.register
class RB75Radio(T18Radio):
    """Retevis RB75"""

    VENDOR = 'Retevis'
    MODEL = 'RB75'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=5.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'KVOGRAM'
    _fingerprint = [b'SMP558' + b'\x00']
    _upper = 30
    _mem_params = _upper  # number of channels
    _gmrs = False  # sold as GMRS radio but supports full band TX/RX


@directory.register
class FRSB1Radio(T18Radio):
    """BTECH FRS-B1"""

    VENDOR = 'BTECH'
    MODEL = 'FRS-B1'
    ACK_BLOCK = True

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'PROGRAM'
    _fingerprint = [b'P3107' + b'\xf7\x00']
    _upper = 22
    _mem_params = _upper  # number of channels
    _frs = True


@directory.register
class RB19Radio(T18Radio):
    """Retevis RB19"""

    VENDOR = 'Retevis'
    MODEL = 'RB19'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'9COGRAM'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 22
    _mem_params = _upper  # number of channels
    _frs = True


@directory.register
class RB19PRadio(T18Radio):
    """Retevis RB19P"""

    VENDOR = 'Retevis'
    MODEL = 'RB19P'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=3.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'70OGRAM'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 30
    _mem_params = _upper  # number of channels
    _gmrs = True


@directory.register
class RB619Radio(T18Radio):
    """Retevis RB619"""

    VENDOR = 'Retevis'
    MODEL = 'RB619'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=0.500),
        chirp_common.PowerLevel('Low', watts=0.499),
    ]

    _magic = b'9COGRAM'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 16
    _mem_params = _upper  # number of channels
    _pmr = True


@directory.register
class RT47Radio(T18Radio):
    """Retevis RT47"""

    VENDOR = 'Retevis'
    MODEL = 'RT47'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.000),
        chirp_common.PowerLevel('Low', watts=0.500),
    ]

    _magic = b'47OGRAM'
    _fingerprint = [b'\x06\x00\x00\x00\x00\x00\x00\x00']
    _upper = 16
    _mem_params = _upper  # number of channels
    _frs16 = True
    _echo = True


@directory.register
class RT47VRadio(RT47Radio):
    """Retevis RT47V"""

    VENDOR = 'Retevis'
    MODEL = 'RT47V'

    VALID_BANDS = [(136000000, 174000000)]

    _upper = 5
    _mem_params = _upper  # number of channels
    _frs16 = False
    _murs = True


@directory.register
class RT647Radio(RT47Radio):
    """Retevis RT647"""

    VENDOR = 'Retevis'
    MODEL = 'RT647'

    _frs16 = False
    _pmr = True


@directory.register
class BFV8ARadio(T18Radio):
    """Baofeng BF-V8A"""

    VENDOR = 'Baofeng'
    MODEL = 'BF-V8A'
    ACK_BLOCK = True

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.000),
        chirp_common.PowerLevel('Low', watts=0.500),
    ]

    _magic = b'PROGRAM'
    _fingerprint = [b'P3107' + b'\xf7\x00\x00']
    _upper = 16
    _mem_params = _upper  # number of channels
    _echo = False


@directory.register
class RB29Radio(T18Radio):
    """Retevis RB29"""

    VENDOR = 'Retevis'
    MODEL = 'RB29'
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'S19GRAM'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 16
    _mem_params = _upper  # number of channels
    _frs16 = True


@directory.register
class RB629Radio(RB29Radio):
    """Retevis RB29"""

    VENDOR = 'Retevis'
    MODEL = 'RB629'

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=0.500),
        chirp_common.PowerLevel('Low', watts=0.499),
    ]

    _frs16 = False
    _pmr = True


@directory.register
class RT15Radio(T18Radio):
    """Retevis RT15"""

    VENDOR = 'Retevis'
    MODEL = 'RT15'
    ACK_BLOCK = False
    CMD_EXIT = b'b'

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'KAOGRAM'
    _fingerprint = [
        b'\x06\x00\x00\x00\x00\x00\x00\x00',
        b'\x06\x03\xe8\x08\xff\xff\xff\xff',
    ]
    _upper = 16
    _mem_params = _upper  # number of channels
    _frs16 = False  # sold as FRS radio but supports full band TX/RX

    @classmethod
    def match_model(cls, filedata, filename):
        # This radio has always been post-metadata, so never do
        # old-school detection
        return False


@directory.register
class RB87Radio(T18Radio):
    """Retevis RB87"""

    VENDOR = 'Retevis'
    MODEL = 'RB87'
    ACK_BLOCK = False
    CMD_EXIT = b''
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=5.00),
        chirp_common.PowerLevel('Low', watts=0.50),
    ]

    _magic = b'C8OGRAN'
    _fingerprint = [b'SMP558']
    _upper = 30
    _mem_params = _upper  # number of channels
    _gmrs = True


MEM_FORMAT_T20FRS = """
// #seekto 0x0000;
struct {
    lbcd rxfreq[4];
    lbcd txfreq[4];
    lbcd rxtone[2];
    lbcd txtone[2];
    u8 jumpcode:1,
       unknown1:2,
       skip:1,
       highpower:1,
       narrow:1,
       unknown2:1,
       bcl:1;
    u8 unknown3[3];
} memory[%d];
#seekto 0x02B0;
struct {
    u8 voicesw;      // Voice SW            +
    u8 voiceselect;  // Voice Select
    u8 scan;         // Scan                +
    u8 vox;          // VOX                 +
    u8 voxgain;      // Vox Gain            +
    u8 voxnotxonrx;  // Rx Disable Vox      +
    u8 hivoltnotx;   // High Vol Inhibit TX +
    u8 lovoltnotx;   // Low Vol Inhibit TX  +
    u8 rxemergency;  // RX Emergency
} settings2;
#seekto 0x02C0;
struct {
    u8 unk:6,
       batterysaver:1,
       beep:1;
    u8 squelchlevel;
    u8 sidekey2;
    u8 timeouttimer;
} settings;
"""


@directory.register
class BFT20FRSRadio(T18Radio):
    """Baofeng BF-T20FRS"""

    VENDOR = 'Baofeng'
    MODEL = 'BF-T20FRS'
    ACK_BLOCK = True

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.000),
        chirp_common.PowerLevel('Low', watts=0.500),
    ]

    _magic = b'PROGRAM'
    _fingerprint = [b'P3107' + b'\xf7\x00\x00']
    _upper = 22
    _mem_params = _upper  # number of channels
    _frs = False  # sold as FRS radio but supports full band TX/RX

    _ranges = [
        (0x0000, 0x0160),
        (0x02B0, 0x02D0),
    ]
    _memsize = 0x03F0

    def process_mmap(self):
        self._memobj = bitwise.parse(
            MEM_FORMAT_T20FRS % self._mem_params, self._mmap
        )


@directory.register
class H777HFRSRadio(T18Radio):
    """Retevis H777H FRS"""

    VENDOR = 'Retevis'
    MODEL = 'H777H_FRS'  # SKU: A9104J
    ACK_BLOCK = False

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=2.000),
        chirp_common.PowerLevel('Low', watts=0.500),
    ]

    TIMEOUTTIMER_LIST = [
        'Off',
        '30 seconds',
        '60 seconds',
        '90 seconds',
        '120 seconds',
        '150 seconds',
        '180 seconds',
    ]

    _magic = b'C701RAD'
    _fingerprint = [b'SMP558' + b'\x02']
    _upper = 16
    _mem_params = _upper  # number of channels
    _reserved = True
    _frs16 = True
    _pmr = False


@directory.register
class H777HPMRRadio(H777HFRSRadio):
    """Retevis H777H PMR"""

    VENDOR = 'Retevis'
    MODEL = 'H777H_PMR'  # SKU: A9104K

    POWER_LEVELS = [
        chirp_common.PowerLevel('High', watts=0.500),
        chirp_common.PowerLevel('Low', watts=0.500),
    ]

    _frs16 = False
    _pmr = True


@directory.register
class BoblovX3Plus(SixteenChannelRadio):
    """Boblov X3 Plus motorcycle/cycling helmet radio"""

    VENDOR = 'Boblov'
    MODEL = 'X3Plus'
