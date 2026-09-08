"""Measure decoded live audio, not just whether the player clock is advancing.
Run in the API container: python scripts/check_audio_level.py
"""
import json
import re
import subprocess
import httpx

with httpx.Client(base_url='http://127.0.0.1:8000',timeout=20) as client:
    client.get('/').raise_for_status()
    status=client.get('/api/status').json()
    assert status['play'], 'The station is not currently transmitting'
    recording=bytearray()
    with client.stream('GET','/api/live') as response:
        response.raise_for_status()
        for block in response.iter_bytes(4096):
            recording.extend(block)
            if len(recording)>=128000:
                break
result=subprocess.run(['ffmpeg','-hide_banner','-i','pipe:0','-af','volumedetect','-f','null','-'],
                      input=bytes(recording),capture_output=True,check=True,timeout=20)
report=result.stderr.decode()
mean=float(re.search(r'mean_volume: ([-\d.]+) dB',report)[1])
peak=float(re.search(r'max_volume: ([-\d.]+) dB',report)[1])
print(json.dumps({'received_bytes':len(recording),'mean_dbfs':mean,'peak_dbfs':peak,'demo':status['demo']}))
if status['demo']:
    assert -30 < mean < -10, 'Demo signal is too quiet or too loud'
    assert peak < -1, 'Demo signal is too close to clipping'
