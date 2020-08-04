import pytest
from timeflux.core.exceptions import ValidationError
from timeflux_hackeeg.nodes.driver import HackEEG

def test_invalid_rate():
    with pytest.raises(ValueError) as e:
        HackEEG(port=None, rate=1)
    assert str(e.value) == "`1` is not a valid rate; valid rates are: [250, 500, 1024, 2048, 4096, 8192, 16384]"

def test_invalid_gain():
    with pytest.raises(ValueError) as e:
        HackEEG(port=None, gain=0)
    assert str(e.value) == "`0` is not a valid gain; valid gains are: [1, 2, 4, 6, 8, 12, 24]"