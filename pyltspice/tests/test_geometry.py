from pyltspice.model.geometry import (TextFrame, apply, mirror_orient, orient_matrix,
                                      rotate_orient)


def test_r90_maps_like_ltspice():
    # resistor pin (16,16) of SYMBOL res 2048 976 R90 lands at (2032, 992)
    x, y = apply(orient_matrix("R90"), 16, 16)
    assert (x + 2048, y + 976) == (2032, 992)


def test_mirrored_orientations():
    assert apply(orient_matrix("M0"), 10, 5) == (-10, 5)
    # IdealTransformer.asc: SYMBOL res -192 160 M90 must put its pins on wire ends
    # (-176, 176) and (-96, 176), so M90 maps (x, y) -> (y, x)
    assert apply(orient_matrix("M90"), 16, 16) == (16, 16)
    assert apply(orient_matrix("M90"), 16, 96) == (96, 16)
    assert apply(orient_matrix("M270"), 10, 5) == (-5, -10)


def test_rotate_cycle_and_mirror_involution():
    o = "R0"
    for _ in range(4):
        o = rotate_orient(o)
    assert o == "R0"
    assert mirror_orient(mirror_orient("R90")) == "R90"


def test_text_stays_readable():
    # horizontal Left text rotated 180 becomes Right-justified, still horizontal
    f = TextFrame.from_just("Left").transformed(orient_matrix("R180"))
    assert not f.vertical and f.to_just() == "Right"
    # VBottom window of an R90 resistor becomes horizontal text sitting above
    f = TextFrame.from_just("VBottom").transformed(orient_matrix("R90"))
    assert not f.vertical and f.to_just() == "Bottom"
    # mirroring swaps left/right justification
    assert TextFrame.from_just("Left").transformed(orient_matrix("M0")).to_just() == "Right"
