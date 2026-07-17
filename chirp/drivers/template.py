# Copyright 2012 Dan Smith <dsmith@danplanet.com>
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

from chirp import bitwise, chirp_common, memmap

LOG = logging.getLogger(__name__)

# Here is where we define the memory map for the radio. Since
# We often just know small bits of it, we can use #seekto to skip
# around as needed.
#
# Our fake radio includes just a single array of ten memory objects,
# With some very basic settings, a 32-bit unsigned integer for the
# frequency (in Hertz) and an eight-character alpha tag
#
MEM_FORMAT = """
#seekto 0x0000;
struct {
  u32 freq;
  char name[8];
} memory[10];
"""


def _download(radio):
    """This is your download function"""
    # NOTE: Remove this in your real implementation!
    return memmap.MemoryMapBytes(b'\x00' * 1000)

    # Get the serial port connection
    serial = radio.pipe

    # Our fake radio is just a simple download of 1000 bytes
    # from the serial port. Do that one byte at a time and
    # store them in the memory map
    data = b''
    for _i in range(0, 1000):
        data += serial.read(1)

    return memmap.MemoryMapBytes(data)


def _upload(radio):
    """This is your upload function"""
    # NOTE: Remove this in your real implementation!
    raise NotImplementedError('This template driver does not really work!')

    # Get the serial port connection
    serial = radio.pipe

    # Our fake radio is just a simple upload of 1000 bytes
    # to the serial port. Do that one byte at a time, reading
    # from our memory map
    for i in range(0, 1000):
        serial.write(radio.get_mmap()[i])


# Uncomment this to actually register this radio in CHIRP
# @directory.register
class TemplateRadio(chirp_common.CloneModeRadio):
    """Acme Template"""
    VENDOR = "Acme"     # Replace this with your vendor
    MODEL = "Template"  # Replace this with your model
    BAUD_RATE = 9600    # Replace this with your baud rate

    # All new drivers should be "Byte Clean" so leave this in place.

    # Return information about this radio's features, including
    # how many memories it has, what bands it supports, etc
    def get_features(self):
        """Override from chirp_common.Radio"""
        rf = chirp_common.RadioFeatures()
        rf.has_bank = False
        rf.memory_bounds = (0, 9)  # This radio supports memories 0-9
        rf.valid_bands = [
            (144000000, 148000000),  # Supports 2-meters
            (440000000, 450000000),  # Supports 70-centimeters
        ]
        return rf

    def get_prompts(self):
        """Override from chirp_common.Radio"""
        pass

    # Extract a high-level memory object from the low-level memory map
    # This is called to populate a memory in the UI
    def get_memory(self, number):
        """Override from chirp_common.Radio"""
        # Arrays are zero-indexed, so channel 1 goes in index 0
        _index = int(number) - 1
        # Get a low-level memory object mapped to the image
        _mem = self._memobj.memory[_index]

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
        """Override from chirp_common.CloneModeRadio"""
        self._mmap = _download(self)
        self.process_mmap()

    # Do an upload of the radio to the serial port
    def sync_out(self):
        """Override from chirp_common.CloneModeRadio"""
        _upload(self)

    # Convert the raw byte array into a memory object structure
    def process_mmap(self):
        """Override from chirp_common.CloneModeRadio"""
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)
