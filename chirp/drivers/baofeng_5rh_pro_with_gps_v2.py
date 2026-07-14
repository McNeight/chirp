# Copyright 2024 Campbell Reed
# Copyright 2025 Mike Iacovacci <ascendr@linuxmail.org>
# Copyright 2026 Dan <dannjb@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Baofeng 5RH Chirp driver"""

import time
import logging
import random

from chirp import bitwise
from chirp import chirp_common
from chirp import directory
from chirp import errors
from chirp import kenwood_tone
from chirp import memmap
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueList,
    RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

# Protocol constants
HEADER_SYNC = bytearray(b"PROGRAM\x00")
HEADER_SYNC_PIC = b"Picture\xff"  # boot-image handshake (no seed, no XOR)
HEADER_INFO = b"INFORMATION"
END_INFO = b"END\x00"

# Accepted boot-image dimensions (width, height)
BOOT_IMAGE_SIZES = [(160, 128), (240, 240), (240, 320)]
T_INFO = bytearray(16)
for _i in range(12, 16):
    T_INFO[_i] = 0xFF

# Data layout
DATA_LEN = 49152
CHN_SIZE = 48
CHN_MAX = 640

# Zone layout (DataProtocol.cs ConvertZone/ZoneConvert). The radio navigates
# channels through zones: each zone holds an FFFF-terminated list of channel
# IDs. A channel only appears on the radio if its ID is in a zone, so the zone
# table must be rebuilt on upload to reflect newly-added channels.
ZONE_TOTAL_OFF = 31360
ZONE_BASE = 31376
ZONE_SIZE = 152
ZONE_MAX = 10
# firmware limit (FormMain.cs:383); 10 * 64 = 640 channels
ZONE_CHN_MAX = 64
# 64 IDs occupy bytes 2..129; 130..135 unused; name 136..151
ZONE_NAME_OFF = 136

TONES = chirp_common.TONES
DTCS = chirp_common.ALL_DTCS_CODES

POWER_LEVELS = [
    chirp_common.PowerLevel("Low", watts=0.5),
    chirp_common.PowerLevel("High", watts=5),
]

DUPLEX = ["", "-", "+", "split"]
MODES = ["FM", "NFM"]

# Frequency coverage reported by the radio (Device Information):
#   RX: 18-200, 200-260, 350-390, 400-600 MHz
#   TX: 136-174, 220-260, 350-390, 400-480 MHz
# The RX ranges are a superset of the TX ranges, so they are used for
# valid_bands (adjacent 18-200/200-260 merged). This also permits cross-band
# memories (e.g. UHF RX with VHF TX).
VALID_BANDS = [
    (18000000, 260000000),
    (350000000, 390000000),
    (400000000, 600000000),
]

# Settings option lists (labels mirror the CPS general-settings form).
# For these the stored byte equals the option index.
SQL_LIST = ["OFF"] + [str(i) for i in range(1, 10)]
TOT_LIST = [str(i * 15) for i in range(15)]          # 0..210s
PRETOT_LIST = [str(i) for i in range(11)]            # 0..10s
APO_LIST = ["OFF", "30", "60", "120", "240", "480"]  # minutes
SAVE_LIST = ["OFF", "1:1", "1:2", "1:4"]
DISP_LIST = ["Frequency", "Name", "Number", "Frequency+Name"]
DUAL_LIST = ["Single band single watch", "Dual band dual watch",
             "Dual band single watch"]
MAINBAND_LIST = ["A", "B"]
VOICE_LIST = ["OFF", "Chinese", "English"]
ENDTONE_LIST = ["OFF", "Mode 1", "Mode 2", "Mode 3"]
HZ1750_LIST = ["1000Hz", "1450Hz", "1750Hz", "2100Hz"]
TAIL_LIST = ["OFF", "55Hz", "120deg", "180deg", "240deg"]
# 1..5
BLIGHTLV_LIST = [str(i) for i in range(1, 6)]
# Special transforms (byte != index):
VOXLV_LIST = [str(i) for i in range(1, 10)]          # byte == int(label)
# byte == val*10
VOXDLY_LIST = ["%.1f" % (1.0 + 0.5 * i) for i in range(19)]
# byte: <5 == Always
BLIGHTTIME_LIST = ["Always"] + [str(i) for i in range(5, 31)]

# key == settings struct field, value == option list (stored byte == index)
_INDEX_SETTINGS = [
    ("sqlv", "Squelch level", SQL_LIST),
    ("tot", "Time-out timer (s)", TOT_LIST),
    ("pre_tot", "TOT pre-alert (s)", PRETOT_LIST),
    ("apo", "Auto power off (min)", APO_LIST),
    ("posave", "Battery save", SAVE_LIST),
    ("dual_mode", "Dual watch mode", DUAL_LIST),
    ("main_band", "Main band", MAINBAND_LIST),
    ("cha_disp", "Display A mode", DISP_LIST),
    ("chb_disp", "Display B mode", DISP_LIST),
    ("voice", "Voice prompt", VOICE_LIST),
    ("endtone", "Roger / end tone", ENDTONE_LIST),
    ("hz1750", "Tone burst", HZ1750_LIST),
    ("tailfreq", "Tail tone", TAIL_LIST),
    ("blight_lv", "Backlight level", BLIGHTLV_LIST),
]

# key == field, label == display name (stored byte == bit, 0/1)
_BOOL_SETTINGS = [
    ("voxsw", "VOX enable"),
    ("busylock", "Busy channel lockout"),
    ("beep", "Key beep"),
    ("keylock", "Key lock"),
    ("autokey", "Auto key lock"),
    ("dispdir", "Display direction"),
    ("enhance", "Enhanced function"),
]


# ============================================================================
# Protocol Functions (from tested v2)
# ============================================================================

def _handshake(radio, is_write=False):
    """Handshake with XOR encryption - exact copy of working Python version."""
    port = radio.pipe
    seed = random.randint(1, 254)

    # H1: Send T_INFO
    port.write(bytes(T_INFO))

    # H2: Wait for response, potentially switch baud
    got_h2 = False
    for _ in range(25):
        time.sleep(0.2)
        if port.in_waiting <= 0:
            continue
        rb = port.read(1)
        if not rb:
            continue
        rb = rb[0]

        if rb != 0x41:
            # Switch to 115200 - close, reopen, reset buffer
            port.close()
            port.baudrate = 115200
            port.open()
            port.reset_input_buffer()

        # Send PROGRAM with seed
        HEADER_SYNC[7] = seed
        port.write(HEADER_SYNC)
        got_h2 = True
        break

    if not got_h2:
        raise errors.RadioError("H2 timeout")

    # H3: Receive encrypted 0x41
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            buf = port.read(1)[0]
            result = seed ^ buf
            if result != 0x41:
                raise errors.RadioError(f"H3 failed: XOR result 0x{result:02X}")
            break
        time.sleep(0.01)
    else:
        raise errors.RadioError("H3 timeout")

    # H4: Send password (8 bytes of seed XOR 0xFF)
    password = bytes([seed ^ 0xFF] * 8)
    port.write(password)

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            buf = port.read(1)[0]
            result = seed ^ buf
            if result != 0x41:
                raise errors.RadioError(f"H4 failed: XOR result 0x{result:02X}")
            break
        time.sleep(0.01)
    else:
        raise errors.RadioError("H4 timeout")

    # H5: Send encrypted HEADER_INFO
    info_xor = bytes([seed ^ b for b in HEADER_INFO])
    port.write(info_xor)

    # Read model info
    time.sleep(0.1)
    if port.in_waiting > 0:
        model_data = port.read(min(port.in_waiting, 16))
        model_str = "".join(
            chr(b ^ seed) if b != 0xFF else "" for b in model_data
        ).strip()
        LOG.info("Radio model: %s", model_str)

    # Send direction (0x52='R' for read, 0x57='W' for write)
    direction = 0x57 if is_write else 0x52
    port.write(bytes([seed ^ direction]))

    # H6: Receive encrypted 0x41
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            buf = port.read(1)[0]
            result = seed ^ buf
            if result != 0x41:
                raise errors.RadioError(f"H6 failed: XOR result 0x{result:02X}")
            break
        time.sleep(0.01)
    else:
        raise errors.RadioError("H6 timeout")

    return seed


def _read_blocks(radio, seed):
    """Read 12 blocks of 4096 bytes each using XOR'd commands"""
    port = radio.pipe
    full = bytearray(DATA_LEN)
    rx_offset = 0
    block_size = 4096
    num_blocks = DATA_LEN // block_size

    port.timeout = 0.5

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Cloning from radio..."
    radio.status_fn(status)

    for block_num in range(num_blocks):
        # Build XOR'd command
        cmd = bytes([
            seed ^ 0x52,
            seed ^ (rx_offset >> 8),
            seed ^ (rx_offset & 0xFF),
            seed
        ])

        port.write(cmd)

        # Read 4100-byte response
        resp = bytearray()
        deadline = time.time() + 6.0
        while len(resp) < 4100 and time.time() < deadline:
            if port.in_waiting > 0:
                chunk = port.read(min(port.in_waiting, 4100 - len(resp)))
                resp.extend(chunk)
            else:
                time.sleep(0.01)

        if len(resp) < 4100:
            raise errors.RadioError(f"Block {block_num}: short read {len(resp)}/4100")

        # Copy payload to buffer (skip 4-byte header)
        full[rx_offset:rx_offset + block_size] = resp[4:4100]
        rx_offset += block_size

        status.cur = block_num + 1
        radio.status_fn(status)

    # Send END command
    end_cmd = bytes([seed ^ b for b in END_INFO])
    port.write(end_cmd)

    # Wait for final ACK
    time.sleep(0.2)
    if port.in_waiting > 0:
        port.read(port.in_waiting)

    # XOR decrypt all data
    for i in range(DATA_LEN):
        full[i] ^= seed

    return bytes(full)


def _write_blocks(radio, seed, data):
    """Write 12 blocks of 4096 bytes each using XOR'd format"""
    port = radio.pipe
    block_size = 4096
    num_blocks = DATA_LEN // block_size
    tx_offset = 0

    port.timeout = 0.5

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Cloning to radio..."
    radio.status_fn(status)

    for block_num in range(num_blocks):
        # Build XOR'd command
        cmd = bytes([
            seed ^ 0x57,  # 0x57 = 'W' for write
            seed ^ (tx_offset >> 8),
            seed ^ (tx_offset & 0xFF),
            seed
        ])

        # Build 4100-byte payload
        chunk = data[tx_offset:tx_offset + block_size]
        if len(chunk) < block_size:
            chunk = chunk + b'\xff' * (block_size - len(chunk))

        # XOR encrypt the payload
        encrypted = bytes([seed ^ b for b in chunk])
        payload = cmd + encrypted

        port.write(payload)

        # Wait for response
        deadline = time.time() + 6.0
        while time.time() < deadline:
            if port.in_waiting > 0:
                resp = port.read(1)[0]
                if (resp ^ seed) == 0x41:
                    break
            else:
                time.sleep(0.01)
        else:
            raise errors.RadioError(f"Block {block_num}: timeout")

        tx_offset += block_size

        status.cur = block_num + 1
        radio.status_fn(status)

    # Send END command
    end_cmd = bytes([seed ^ b for b in END_INFO])
    port.write(end_cmd)

    # Wait for final ACK
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            port.read(1)
            return
        time.sleep(0.01)


# ============================================================================
# Boot image upload
# ============================================================================
# The boot-picture protocol is a simplified, unencrypted variant of the clone
# protocol: a 3-stage handshake (H2 sends "Picture\xFF") followed by raw
# 4096-byte blocks that the radio ACKs with 0x41. No seed, no XOR. Mirrors the
# CPS writePicInfo path; the radio has no read-back for the boot image.

def _handshake_boot(radio):
    """Three-stage unencrypted handshake for the boot-image upload."""
    port = radio.pipe

    # H1: send T_INFO
    port.write(bytes(T_INFO))

    # H2: wait for a byte, switch to 115200 if it isn't an ACK, then send sync
    got_h2 = False
    for _ in range(25):
        time.sleep(0.2)
        if port.in_waiting <= 0:
            continue
        rb = port.read(1)
        if not rb:
            continue
        if rb[0] != 0x41:
            port.close()
            port.baudrate = 115200
            port.open()
            port.reset_input_buffer()
        port.write(HEADER_SYNC_PIC)
        got_h2 = True
        break

    if not got_h2:
        raise errors.RadioError("Boot handshake H2 timeout")

    # H3: expect a raw 0x41 ACK
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            ack = port.read(1)[0]
            if ack != 0x41:
                raise errors.RadioError(
                    "Boot handshake H3 failed: 0x%02X" % ack)
            return
        time.sleep(0.01)
    raise errors.RadioError("Boot handshake H3 timeout")


def _load_boot_image(path):
    """Load a boot image, converting a 24-bit BMP to big-endian RGB565.

    A non-.bmp file is treated as pre-converted raw RGB565 data. Mirrors CPS
    Convert24To16Bit / ReversalHighLowByte (FormProgressBar.cs:506).
    """
    if not str(path).lower().endswith(".bmp"):
        with open(path, "rb") as f:
            return f.read()

    try:
        from PIL import Image
    except ImportError as exc:
        raise errors.RadioError(
            "Pillow is required for BMP conversion (pip install Pillow)"
        ) from exc

    img = Image.open(path)
    w, h = img.size
    if (w, h) not in BOOT_IMAGE_SIZES:
        raise errors.RadioError(
            "Unsupported image size %dx%d (accepted: %s)" %
            (w, h, ", ".join("%dx%d" % s for s in BOOT_IMAGE_SIZES)))

    img = img.convert("RGB")
    data = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b = img.getpixel((x, y))
            px = (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)
            data.append(px >> 8)     # big-endian high byte
            data.append(px & 0xFF)   # big-endian low byte
    return bytes(data)


def _write_boot_image(radio, data):
    """Send the boot image as raw, zero-padded 4096-byte blocks."""
    port = radio.pipe
    port.timeout = 0.5
    block_size = 4096
    num_blocks = (len(data) + block_size - 1) // block_size

    status = chirp_common.Status()
    status.cur = 0
    status.max = num_blocks
    status.msg = "Uploading boot image..."
    radio.status_fn(status)

    sent = 0
    for block_num in range(num_blocks):
        chunk = data[sent:sent + block_size]
        block = bytes(chunk) + b"\x00" * (block_size - len(chunk))
        port.write(block)

        deadline = time.time() + 8.0
        while True:
            if port.in_waiting > 0:
                ack = port.read(1)[0]
                if ack != 0x41:
                    raise errors.RadioError(
                        "Boot block %d bad ACK 0x%02X" % (block_num, ack))
                break
            if time.time() > deadline:
                raise errors.RadioError(
                    "Boot block %d timeout" % block_num)
            time.sleep(0.01)

        sent += len(chunk)
        status.cur = block_num + 1
        radio.status_fn(status)

    # END marker (raw)
    port.write(END_INFO)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if port.in_waiting > 0:
            port.read(port.in_waiting)
            break
        time.sleep(0.01)


def upload_boot_image(radio, path):
    """Convert and upload a boot image to the radio.

    @path is a 24-bit BMP (160x128, 240x240 or 240x320) or pre-converted
    raw RGB565 data.
    """
    LOG.info("Uploading boot image from %s", path)
    port = radio.pipe
    port.timeout = 0.1
    port.baudrate = 19200

    data = _load_boot_image(path)
    LOG.info("Boot image: %d bytes RGB565", len(data))
    try:
        _handshake_boot(radio)
        _write_boot_image(radio, data)
        LOG.info("Boot image upload complete")
    except Exception as e:
        raise errors.RadioError("Boot image upload failed: %s" % e)


# ============================================================================
# Chirp Interface
# ============================================================================

MEM_FORMAT = """
#seekto 0x0080;
struct {
  lbcd rxfreq;     // 0  (little-endian)
  lbcd txfreq;     // 4  (little-endian)
  ul16 rxtone;     // 8-9   (decode / receive sub-audio)
  ul16 txtone;     // 10-11 (encode / transmit sub-audio)
  u8 unknown1[4];  // 12-15
  u8 flags1;       // 16    power[7:6] wideth[5] offsetdir[3:2] freqinvert[1] talkaround[0]
  u8 flags2;       // 17    fivetoneptt[7:6] dtmfptt[5:4] sqtype[3:0]
  u8 unknown2[14]; // 18-31
  char name[16];   // 32-47 GB2312
} memory[640];

#seekto 0x7980;
struct {
  u8 cha_mode;                                                  // 0
  u8 chb_mode;                                                  // 1
  u16 cha_num;                                                  // 2
  u16 chb_num;                                                  // 4
  u8 cha_zone;                                                  // 6
  u8 chb_zone;                                                  // 7
  u8 blight_time;                                               // 8
  u8 blight_lv;                                                 // 9
  u8 cha_disp:4, chb_disp:4;                                    // 10
  u8 dual_mode;                                                 // 11
  u8 main_band;                                                 // 12
  u8 sqlv;                                                      // 13
  u8 vox_lv;                                                    // 14
  u8 vox_dly;                                                   // 15
  u8 posave;                                                    // 16
  u8 posave_dly;                                                // 17
  u8 lone_work_tim;                                             // 18
  u8 lone_work_rsp;                                             // 19
  u8 apo;                                                       // 20
  u8 tot;                                                       // 21
  u8 pre_tot;                                                   // 22
  u8 unknown23;                                                 // 23
  u8 gps_zone;                                                  // 24
  u8 unknown25;                                                 // 25
  u8 hz1750;                                                    // 26
  u8 unknown27[3];                                              // 27-29
  u8 noaa_ch;                                                   // 30
  u8 gps_id;                                                    // 31
  u8 voxsw:1, aprssw:1, lonework:1, daodi:1, voice:2, busylock:2; // 32
  u8 keylock:1, autokey:1, unknown33:6;                        // 33
  u8 beep:1, endtone:2, unknown34:5;                           // 34
  u8 flag35;                                                    // 35
  u8 flag36;                                                    // 36
  u8 flag37;                                                    // 37
  u8 tailfreq:3, noaa:1, dispdir:1, fminter:1, noisecancel:1, enhance:1; // 38
  u8 unknown39;                                                 // 39
  u8 bt_hold;                                                   // 40
  u8 bt_rxdly;                                                  // 41
  u8 bt_mic;                                                    // 42
  u8 bt_spk;                                                    // 43
  u8 bt_password[4];                                            // 44-47
  u8 skey1;                                                     // 48
  u8 skey2;                                                     // 49
  u8 lkey1;                                                     // 50
  u8 lkey2;                                                     // 51
  u8 unknown52[12];                                             // 52-63
  u8 pow_password[8];                                           // 64-71
  u8 wr_password[8];                                            // 72-79
  char radio_name[16];                                          // 80-95
  char bluet_name[16];                                          // 96-111
  char pair_name[16];                                           // 112-127
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


def _download(radio):
    """Download from radio"""
    LOG.info("Downloading from Baofeng 5RH")
    port = radio.pipe
    port.timeout = 0.1
    port.baudrate = 19200

    try:
        seed = _handshake(radio, is_write=False)
        LOG.info("Handshake complete, seed=0x%02X", seed)
        data = _read_blocks(radio, seed)
        LOG.info("Downloaded %d bytes", len(data))
        return data
    except Exception as e:
        raise errors.RadioError(f"Download failed: {e}")


def _upload(radio, data):
    """Upload to radio"""
    LOG.info("Uploading to Baofeng 5RH")
    port = radio.pipe
    port.timeout = 0.1
    port.baudrate = 19200

    try:
        seed = _handshake(radio, is_write=True)
        LOG.info("Handshake complete, seed=0x%02X", seed)
        _write_blocks(radio, seed, data)
        LOG.info("Uploaded %d bytes", len(data))
    except Exception as e:
        raise errors.RadioError(f"Upload failed: {e}")


@directory.register
class BaofengUV5RHRadio(chirp_common.CloneModeRadio):
    """Baofeng 5RH"""
    VENDOR = "Baofeng"
    MODEL = "5RH Pro with GPS (v2)"
    BAUD_RATE = 19200

    _tone_model = kenwood_tone.KenwoodToneModel(
        dcs_base=0x2800, pol_mask=0x8000, tone_init=0xFFFF, tone_flag=0x0000
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._boot_image_path = ""
        self._boot_image_data = None
        self._model = ""

    @classmethod
    def get_prompts(cls):
        rp = chirp_common.RadioPrompts()
        rp.experimental = _(
            "This driver is a beta version.\n"
            "\n"
            "Please save an unedited copy of your first successful\n"
            "download to a CHIRP Radio Images(*.img) file."
        )
        rp.pre_download = _(
            "Follow these steps to download:\n"
            "1. Turn off radio\n"
            "2. Connect programming cable\n"
            "3. Turn on radio\n"
            "4. Click OK\n"
        )
        rp.pre_upload = _(
            "Follow these steps to upload:\n"
            "1. Turn off radio\n"
            "2. Connect programming cable\n"
            "3. Turn on radio\n"
            "4. Click OK\n"
        )
        return rp

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_tuning_step = True
        rf.has_name = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_ctone = True

        rf.valid_bands = VALID_BANDS
        rf.valid_modes = MODES
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS"]
        rf.valid_duplexes = DUPLEX
        rf.valid_power_levels = POWER_LEVELS
        rf.valid_tones = TONES
        rf.valid_dtcs_codes = DTCS

        rf.memory_bounds = (1, 640)
        rf.valid_name_length = 16

        return rf

    def sync_in(self):
        self._mmap = memmap.MemoryMapBytes(_download(self))
        self.process_mmap()

    def sync_out(self):
        self._rebuild_zones()
        _upload(self, self._mmap.get_packed())

    def _rebuild_zones(self):
        """Regenerate the zone tables so every in-use channel is reachable.

        The radio displays channels via each zone's FFFF-terminated ID list
        (see DataProtocol.cs:1828). Chirp has no zone concept, so map channels
        to zones naturally (zone z holds channels [z*67 .. z*67+67)) and write
        the ID for each in-use channel, FFFF otherwise. Zone names are
        preserved; an empty name on a populated zone gets a "Zone N" default.
        """
        mm = self._mmap
        zones_used = 0
        for z in range(ZONE_MAX):
            zbase = ZONE_BASE + z * ZONE_SIZE
            count = 0
            for idx in range(ZONE_CHN_MAX):
                ch_index = z * ZONE_CHN_MAX + idx
                off = zbase + 2 + idx * 2
                if ch_index < CHN_MAX and self._memobj.chan_empty.bitfield[ch_index]:
                    mm[off] = (ch_index >> 8) & 0xFF   # ID high byte
                    mm[off + 1] = ch_index & 0xFF      # ID low byte
                    count += 1
                else:
                    mm[off] = 0xFF
                    mm[off + 1] = 0xFF
            mm[zbase] = count
            mm[zbase + 1] = 0xFF
            if count:
                zones_used += 1
                name_off = zbase + ZONE_NAME_OFF
                if mm[name_off][0] in (0x00, 0xFF):
                    default = ("Zone %d" % (z + 1)).encode('ascii')[:16]
                    padded = default.ljust(16, b'\x00')
                    for i in range(16):
                        mm[name_off + i] = padded[i]
        mm[ZONE_TOTAL_OFF] = zones_used

    def upload_boot_image(self, path):
        """Convert and upload a boot image (24-bit BMP or raw RGB565)."""
        upload_boot_image(self, path)

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def get_memory(self, number):
        mem = chirp_common.Memory()
        mem.number = number
        _index = number - 1

        # Check if this memory is present in the occupied list
        mem.empty = self._memobj.chan_empty.bitfield[_index] == 1

        if mem.empty:
            return mem

        _mem = self._memobj.memory[_index]

        # Frequencies
        mem.freq = int(_mem.rxfreq) * 10

        # Duplex
        if int(_mem.txfreq) == int(_mem.rxfreq):
            mem.duplex = ""
            mem.offset = 0
        elif int(_mem.txfreq) == 0:
            mem.duplex = "off"
            mem.offset = 0
        elif int(_mem.txfreq) > int(_mem.rxfreq):
            mem.duplex = "+"
            mem.offset = (int(_mem.txfreq) - int(_mem.rxfreq)) * 10
        elif int(_mem.rxfreq) > int(_mem.txfreq):
            mem.duplex = "-"
            mem.offset = (int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        # Tones
        self._tone_model.get_tone(_mem, mem)

        # Power (stored field value 2 == High, 0 == Low)
        power_idx = (int(_mem.flags1) >> 6) & 0x03
        mem.power = POWER_LEVELS[1] if power_idx >= 2 else POWER_LEVELS[0]

        # Mode (wideth bit: wide == FM, narrow == NFM)
        bw = (int(_mem.flags1) >> 4) & 0x03
        mem.mode = "NFM" if bw == 0 else "FM"

        # Name (GB2312 encoded, stops at 0x00 or 0xFF)
        raw = _mem.get_raw(asbytes=True)
        name_bytes = bytearray()
        for i in range(32, 48):
            if raw[i] in (0xFF, 0x00):
                break
            name_bytes.append(raw[i])
        try:
            mem.name = name_bytes.decode('gb2312').rstrip()
        except UnicodeDecodeError:
            mem.name = name_bytes.decode('latin-1', errors='replace').rstrip()

        return mem

    def set_memory(self, memory):
        _index = memory.number - 1
        if memory.empty:
            self._memobj.memory[_index].set_raw(b"\x00" * CHN_SIZE)
            self._memobj.chan_empty.bitfield[_index] = 1
            return

        _mem = self._memobj.memory[_index]

        # Clear the slot first (CPS zero-fills before writing known fields)
        _mem.set_raw(b"\x00" * CHN_SIZE)

        # Frequency (convert to BCD-in-hex)
        _mem.rxfreq = memory.freq // 10

        if memory.duplex == "off":
            _mem.txfreq.set_raw(b"\xff\xff\xff\xff")
        elif memory.duplex == "split":
            _mem.txfreq = memory.offset // 10
        elif memory.duplex == "+":
            _mem.txfreq = (memory.freq + memory.offset) // 10
        elif memory.duplex == "-":
            _mem.txfreq = (memory.freq - memory.offset) // 10
        else:
            _mem.txfreq = memory.freq // 10

        # Tones
        self._tone_model.set_tone(memory, _mem)

        # flags1: power[7:6] (High == 2), wideth[5] (wide == FM)
        flags1 = 0
        if memory.power == POWER_LEVELS[1]:
            flags1 |= 2 << 6
        if memory.mode == "FM":
            flags1 |= 0x20
        _mem.flags1 = flags1

        # Name (GB2312 encoded, pad with 0x00 like CPS StringSwap2Char)
        name = memory.name or ""
        try:
            name_bytes = name.encode('gb2312')
        except UnicodeEncodeError:
            name_bytes = name.encode('ascii', errors='ignore')
        _mem.name = name_bytes[:16].ljust(16, b'\x00')
        self._memobj.chan_empty.bitfield[_index] = 0
        self._memobj.chan_empty.bitfield[_index] = 0

    def get_settings(self):
        _s = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic")
        group = RadioSettings(basic)

        def _list(key, name, options, idx):
            if idx < 0 or idx >= len(options):
                idx = 0
            rs = RadioSetting(key, name,
                              RadioSettingValueList(options, current_index=idx))
            basic.append(rs)

        for key, name, options in _INDEX_SETTINGS:
            _list(key, name, options, int(getattr(_s, key)))

        # Special transforms
        _list("vox_lv", "VOX level", VOXLV_LIST, int(_s.vox_lv) - 1)

        dly = (int(_s.vox_dly) - 10) // 5
        _list("vox_dly", "VOX delay (s)", VOXDLY_LIST, dly)

        bt = int(_s.blight_time)
        bt_idx = 0 if bt < 5 else min(bt - 4, len(BLIGHTTIME_LIST) - 1)
        _list("blight_time", "Backlight time (s)", BLIGHTTIME_LIST, bt_idx)

        for key, name in _BOOL_SETTINGS:
            rs = RadioSetting(key, name,
                              RadioSettingValueBoolean(bool(int(getattr(_s, key)))))
            basic.append(rs)

        # Radio name (GB2312, terminated by 0x00/0xFF)
        raw = _s.get_raw(asbytes=True)
        nb = bytearray()
        for b in raw[80:96]:
            if b in (0x00, 0xFF):
                break
            nb.append(b)
        try:
            cur_name = nb.decode('gb2312')
        except UnicodeDecodeError:
            cur_name = nb.decode('latin-1', errors='replace')
        rs = RadioSetting("radio_name", "Radio name",
                          RadioSettingValueString(0, 16, cur_name))
        basic.append(rs)

        return group

    def set_settings(self, settings):
        _s = self._memobj.settings
        index_map = {k: opts for k, _, opts in _INDEX_SETTINGS}

        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue

            key = element.get_name()
            val = element.value

            if key in index_map:
                setattr(_s, key, index_map[key].index(str(val)))
            elif key == "vox_lv":
                _s.vox_lv = int(str(val))
            elif key == "vox_dly":
                _s.vox_dly = int(round(float(str(val)) * 10))
            elif key == "blight_time":
                s = str(val)
                _s.blight_time = 0 if s == "Always" else int(s)
            elif key == "radio_name":
                name = str(val).rstrip()  # strip trailing pad spaces
                try:
                    nb = name.encode('gb2312')
                except UnicodeEncodeError:
                    nb = name.encode('ascii', errors='ignore')
                _s.radio_name = nb[:16].ljust(16, b'\x00')
            else:
                setattr(_s, key, 1 if bool(val) else 0)
