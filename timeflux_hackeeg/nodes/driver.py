# import sys
import numpy as np
import hackeeg
from hackeeg import ads1299
from hackeeg.driver import SPEEDS, GAINS, Status
from timeflux.core.node import Node
from timeflux.helpers.clock import now
from threading import Thread, Lock
from time import sleep, time


class HackEEG(Node):

    """HackEEG driver.

    Attributes:
        o (Port): Default output, provides DataFrame.

    Args:
        port (string): The serial port.
            e.g. ``COM3`` on Windows;  ``/dev/cu.usbmodem14601`` on MacOS;
            ``/dev/ttyUSB0`` on GNU/Linux.
        rate (int): The device rate in Hz.
            Allowed values: ``250``, ``500``, ``1024``, ``2048``, ``4096``, ``8192``,
            ``16384``. Default: ``250``.
        gain (int): The amplifier gain.
            Allowed values: ``1``, ``2``, ``4``, ``6``, ``8``, ``12``, ``24``.
            Default: ``24``.
        channels (int): The number of channels to enable. Default: ``8``.
        debug (bool): If ``True``, print debug information. Default: ``False``.

    Example:
        .. literalinclude:: /../examples/simple.yaml
           :language: yaml

    """

    def __init__(self, port, rate=250, gain=24, channels=8, debug=False):

        # Validate input
        if rate not in SPEEDS.keys():
            raise ValueError(
                f"`{rate}` is not a valid rate; valid rates are: {sorted(SPEEDS.keys())}"
            )
        if gain not in GAINS.keys():
            raise ValueError(
                f"`{gain}` is not a valid gain; valid gains are: {sorted(GAINS.keys())}"
            )

        # Setup board
        self._hackeeg = hackeeg.HackEEGBoard(port, baudrate=2000000, debug=debug)
        self._hackeeg.connect()
        self._hackeeg.stop_and_sdatac_messagepack()
        self._hackeeg.sdatac()
        self._hackeeg.blink_board_led()
        self._hackeeg.wreg(ads1299.CONFIG1, SPEEDS[rate] | ads1299.CONFIG1_const)
        self._hackeeg.disable_all_channels()
        for channel in range(1, channels + 1):
            self._hackeeg.wreg(
                ads1299.CHnSET + channel, ads1299.ELECTRODE_INPUT | GAINS[gain]
            )
        self._hackeeg.wreg(ads1299.MISC1, ads1299.SRB1 | ads1299.MISC1_const)
        self._hackeeg.wreg(ads1299.MISC1, ads1299.MISC1_const)
        self._hackeeg.messagepack_mode()
        self._hackeeg.start()
        self._hackeeg.rdatac()

        # Compute time offset
        now = time() * 1e6
        row = self._read()
        self._offset = now - row[1]

        # Remember sample count
        self._count = row[0]
        self._missed = 0

        # Set meta
        self.meta = {"rate": rate}

        # Launch background thread
        self._reset()
        self._lock = Lock()
        self._running = True
        self._thread = Thread(target=self._loop).start()

    def _reset(self):
        """Empty cache.
        """
        self._rows = []
        self._timestamps = []

    def _loop(self):
        """Acquire and cache data.
        """
        while self._running:
            try:
                row = self._read()
                if row:
                    self._check(row[0])
                    timestamp = np.datetime64(int(row[1] + self._offset), "us")
                    self._lock.acquire()  # `with self.lock:` is about twice as slow
                    self._timestamps.append(timestamp)
                    self._rows.append(row[2])
                    self._lock.release()
            except:
                pass

    def _check(self, count):
        """Report dropped samples.

        We don't even bother about a possible overflow of the sample counter as it
        would take about 3 days at 16K SPS before reaching the maximum value.
        """
        missed = (count - self._count) - 1
        self._count = count
        if missed:
            self._missed += missed
        else:
            if self._missed:
                self.logger.warn(f"Missed {self._missed} samples")
                self._missed = 0

    def _read(self):
        """Read a line of data from the device.
        """
        row = False
        result = self._hackeeg.read_rdatac_response()
        if result:
            status_code = result.get(self._hackeeg.MpStatusCodeKey)
            data = result.get(self._hackeeg.MpDataKey)
            if status_code == Status.Ok and data:
                decoded_data = result.get(self._hackeeg.DecodedDataKey)
                if decoded_data:
                    values = []
                    channel_data = decoded_data.get("channel_data")
                    for channel_number, sample in enumerate(channel_data):
                        values.append(sample)
                    row = (
                        decoded_data.get("sample_number"),
                        decoded_data.get("timestamp"),
                        values,
                    )
        return row

    def update(self):
        """Update the node output.
        """
        with self._lock:
            if self._rows:
                self.o.set(self._rows, self._timestamps, meta=self.meta)
                self._reset()

    def terminate(self):
        """Cleanup.
        """
        self._running = False
        while self._thread and self._thread.is_alive():
            sleep(0.001)
        if self._hackeeg:
            try:
                self._hackeeg.stop_and_sdatac_messagepack()
                self._hackeeg.blink_board_led()
            except:
                pass
