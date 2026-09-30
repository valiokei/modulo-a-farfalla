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


@pytest.mark.parametrize("shape", [
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
