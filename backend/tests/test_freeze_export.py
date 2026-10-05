"""Real moving frames and audio: a static source cannot prove a freeze works."""
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from app.media import encode_h264, probe
from app.telestration import annotation_freeze, annotation_layers


def frame(path, time):
    result = subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(path),
        '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=30)
    return np.frombuffer(result.stdout,dtype=np.uint8).reshape(180,320,3).astype(float)


@pytest.mark.parametrize('at,audio', [(0,False),(1,True),(2.8,False)])
def test_real_freeze_insert_preserves_motion_and_audio(tmp_path,monkeypatch,at,audio):
    monkeypatch.setattr('app.media.hardware_backend',lambda:'cpu')
    source=tmp_path/'moving.mp4';output=tmp_path/'paused.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=320x180:r=25',
        *(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000'] if audio else []),
        '-t','4','-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,timeout=30)
    digest=hashlib.sha256(source.read_bytes()).digest()
    # Event/annotation are in match time; clip seeks are in this camera's time.
    event=SimpleNamespace(start=11,end=14,timestamp=11+at)
    annotation=SimpleNamespace(timestamp=11+at,start=11,end=14,coordinate_mode='screen',shapes=[
        {'type':'line','x1':.1,'y1':.25,'x2':.9,'y2':.25,'color':'#ffdf36','lineWidth':12}])
    freeze=annotation_freeze(annotation,source,1,4,2,time_offset=10)
    with annotation_layers(annotation,event,source,1,4,output,time_offset=10,freeze=freeze) as layers:
        encode_h264(source,output,start=1,end=4,overlays=layers,freeze=freeze)
    info=probe(output)
    assert abs(float(info['format']['duration'])-5)<.15
    first,second=frame(output,at+.3),frame(output,at+1.6)
    assert np.abs(first-second).mean()<1, 'Frames must remain still throughout inserted hold'
    stripe=first[43:48,40:280]
    assert ((stripe[:,:,0]>180)&(stripe[:,:,1]>160)&(stripe[:,:,2]<120)).sum()>800
    assert np.abs(frame(source,1+at)-frame(source,min(3.95,1+at+.6))).mean()>2, 'Source fixture must actually move'
    assert np.abs(first[60:]-frame(source,1+at)[60:]).mean()<5, 'Hold must use the saved source frame'
    # After the hold the original source time, not at+hold seconds, resumes.
    remaining=min(.08,(3-at)/2)
    assert np.abs(frame(output,at+2+remaining)[60:]-frame(source,1+at+remaining)[60:]).mean()<6
    if audio:
        def rms(time):
            data=subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(output),'-t','0.2',
                '-vn','-f','f32le','-ac','1','-'],capture_output=True,check=True,timeout=30).stdout
            return np.sqrt(np.mean(np.frombuffer(data,dtype='<f4')**2))
        assert rms(.3)>.03 and rms(at+.5)<.001 and rms(at+2+.3)>.03
    else: assert not any(s['codec_type']=='audio' for s in info['streams'])
    assert hashlib.sha256(source.read_bytes()).digest()==digest
    assert not list(tmp_path.glob('*-ink-*'))


def test_freeze_validation_and_anchors(monkeypatch):
    monkeypatch.setattr('app.telestration.probe',lambda _:pytest.fail('Must not probe'))
    assert annotation_freeze(None,Path('source'),0,3,3) is None
    for seconds in (-1,11,float('nan')):
        with pytest.raises(ValueError):annotation_freeze(None,'source',0,3,seconds)
    # A requested pause anchors to the event timestamp even without drawings,
    # and a stale drawing timestamp is clamped inside the clip, not dropped.
    monkeypatch.setattr('app.telestration.probe',lambda _:{"streams":[]})
    assert annotation_freeze(None,'source',0,3,2,event=SimpleNamespace(timestamp=1.5))==(1.5,2,False)
    stale=annotation_freeze(SimpleNamespace(timestamp=9,shapes=[{}]),'source',0,3,2)
    assert stale is not None and stale[1:]==(2,False) and stale[0]==pytest.approx(2.96)


def test_freeze_without_active_drawings_keeps_the_hold(tmp_path,monkeypatch):
    monkeypatch.setattr('app.telestration.probe',lambda _: {"streams":[{"codec_type":"video","width":640,"height":360}]})
    event=SimpleNamespace(start=0,end=4,timestamp=1)
    annotation=SimpleNamespace(coordinate_mode="screen",start=0,end=4,shapes=[
        {"type":"pen","points":[[.1,.3],[.8,.3]],"color":"#ffdf36","start":2,"end":3}])
    # The only drawing appears from t=2, after the hold at t=1: the pause must
    # still export, simply without ink on the frozen frame.
    with annotation_layers(annotation,event,Path("original.mp4"),0,4,tmp_path/"clip.mp4",freeze=(1,2,False)) as layers:
        assert layers==[]
