from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.telestration import annotation_layers, raster_shape


def test_screen_shapes_use_normalized_coordinates():
    image = raster_shape({"type":"pen", "points":[[.1,.3],[.8,.3]],
                          "color":"#ffdf36", "lineWidth":10}, 1000, 562)
    assert tuple(image[168,450]) == (54,223,255,255)
    assert not image[400,450].any()
    arrow = raster_shape({"type":"arrow", "x1":.1,"y1":.3,"x2":.8,"y2":.3,
                          "color":"#ffdf36"}, 1000, 562)
    assert arrow[168,450,3] == 255
    for kind in ("rectangle","ellipse","polygon","line"):
        assert raster_shape({"type":kind,"x1":.1,"y1":.1,"x2":.8,"y2":.8,
                             "points":[[.1,.1],[.8,.1],[.8,.8]],"color":"#ffdf36"},320,180).any()


def test_text_notes_are_exported_where_the_editor_draws_them():
    shape = {"type":"text","x1":.1,"y1":.2,"x2":.1,"y2":.2,"text":"Pressing alto è ok","size":40,"color":"#ffdf36"}
    image = raster_shape(shape, 1000, 562)
    ys, xs = np.nonzero(image[:,:,3])
    # Top-left anchored at the click point, about one font size tall, yellow fill with a dark outline.
    assert 95 <= xs.min() <= 110 and 98 <= ys.min() <= 125 and ys.max() <= 112 + 50  # the accent of 'è' reaches cap height
    assert ((image[:,:,:3] == (54,223,255)).all(axis=2) & (image[:,:,3] == 255)).any()
    assert ((image[:,:,:3] == (0,0,0)).all(axis=2) & (image[:,:,3] == 255)).any()
    assert not raster_shape({**shape, "text":"   "}, 320, 180).any()


def test_text_export_keeps_accents_fits_the_box_and_rotates():
    base = {"type":"text","x1":.1,"y1":.2,"size":60,"color":"#ffdf36"}
    plain = raster_shape({**base, "text":"e"}, 1000, 562)[:,:,3] > 0
    accented = raster_shape({**base, "text":"è"}, 1000, 562)[:,:,3] > 0
    assert accented.sum() > plain.sum() and np.nonzero(accented)[0].min() < np.nonzero(plain)[0].min() - 5
    assert raster_shape({**base, "text":"Číšník řekl: ďábel ů ü ñ ç ß"}, 1000, 562).any()
    # A box narrower than the Hershey text shrinks it instead of overflowing.
    boxed = raster_shape({**base, "text":"Pressing alto", "x2":.3, "y2":.2 + 60*1000/562/1000}, 1000, 562)
    assert np.nonzero(boxed[:,:,3])[1].max() <= 300 + 8
    flat = np.nonzero(raster_shape({**base, "text":"Pressing", "x2":.4, "y2":.31}, 1000, 562)[:,:,3])
    turned = np.nonzero(raster_shape({**base, "text":"Pressing", "x2":.4, "y2":.31, "rotation":90}, 1000, 562)[:,:,3])
    assert np.ptp(flat[1]) > 2 * np.ptp(flat[0]) and np.ptp(turned[0]) > 2 * np.ptp(turned[1])
    # rotated around the box centre (x 250, y ~141)
    assert abs((turned[1].min() + turned[1].max()) / 2 - 250) < 25 and abs((turned[0].min() + turned[0].max()) / 2 - 143) < 30


@pytest.mark.parametrize("shape", [
    {"type":"text","text":"x"*201},
    {"type":"line","x1":float('nan')},
    {"type":"line","color":"red;movie=evil"},
    {"type":"line","mode":"field"},
    {"type":"unknown"},
    {"type":"pen","points":[[0,0]]*4097},
])
def test_invalid_annotations_fail_closed(shape):
    with pytest.raises(ValueError): raster_shape(shape,320,180)


def test_layer_timing_transparency_and_cleanup(tmp_path,monkeypatch):
    monkeypatch.setattr('app.telestration.probe',lambda _: {"streams":[{"codec_type":"video","width":640,"height":360}]})
    event=SimpleNamespace(start=1,end=5,timestamp=2)
    annotation=SimpleNamespace(coordinate_mode="screen",start=1,end=5,shapes=[
        {"type":"pen","points":[[.1,.3],[.8,.3]],"color":"#ffdf36","start":2,"end":4},
        {"type":"pen","points":[[.1,.6],[.8,.6]],"color":"#ffdf36","start":2,"end":4,"visible":False},
    ])
    with annotation_layers(annotation,event,Path("original.mp4"),1,5,tmp_path/"clip.mp4") as layers:
        assert len(layers)==1
        path,first,last=layers[0]
        assert (first,last)==(1,3)
        image=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
        assert image.shape==(360,640,4) and image[108,200,3]>0
        assert not image[216,200].any()
        directory=path.parent
    assert not directory.exists()
    with pytest.raises(RuntimeError):
        with annotation_layers(annotation,event,Path("original.mp4"),1,5,tmp_path/"clip.mp4") as layers:
            directory=layers[0][0].parent
            raise RuntimeError("Encode failed")
    assert not directory.exists()


def test_empty_annotations_never_probe_or_modify_source(monkeypatch):
    monkeypatch.setattr('app.telestration.probe',lambda _: pytest.fail("No annotation should not probe"))
    with annotation_layers(None,None,"source",0,3,Path("output.mp4")) as layers:
        assert layers==[]
