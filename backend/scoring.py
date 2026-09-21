import math

OPEN = ('pending', 'investigating', 'activity_confirmed')
SEARCH = ('building_collapse', 'trapped_people', 'audio')

def distance(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    d1, d2 = p2-p1, math.radians(b[1]-a[1])
    h = math.sin(d1/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(d2/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))

def risk(kind, value):
    if kind == 'temperature':
        return 'critical' if value < 0 else 'high' if value < 10 else 'medium' if value < 20 else 'low'
    if kind == 'rainfall':
        return 'critical' if value > 10 else 'high' if value >= 5 else 'medium' if value >= 2 else 'low'
    return {1:'low', 2:'medium', 3:'high'}[int(value)]

def calculate(reports, audio, env):
    reports = [r for r in reports if r['verification_status'] != 'rejected']
    audio = [a for a in audio if a['review_status'] != 'false_alarm' and (a['human_type'] or a['review_status'] == 'confirmed_human')]
    collapse = any(r['incident_type'] in SEARCH[:2] or r.get('trapped_people') is True for r in reports)
    repeated = any(a['repeated_signal'] for a in audio)
    both = bool(reports and audio)
    breakdown = {'Citizen reports (2 each; cap 12)':min(12,len(reports)*2), 'Reported collapse or trapped people':3 if collapse else 0, 'Human-type audio (3 each; cap 9)':min(9,len(audio)*3), 'Repeated human-type signal':5 if repeated else 0, 'Report and audio channels':4 if both else 0}
    # PRD 7.2 conflicts with 11.5: landslide is safety context, never a score boost.
    score = sum(breakdown.values())
    return dict(score=score, priority='high' if score>=15 else 'medium' if score>=7 else 'low', breakdown=breakdown, report_count=len(reports), audio_count=len(audio), repeated_signal=repeated, multi_signal=both, is_search_relevant=bool(collapse or audio))

def rank(items):
    queue = sorted([i for i in items if i['status'] in OPEN and i['is_search_relevant']], key=lambda i:(-i['score'], -i['last_signal_at']))
    # Latest human override wins when requested positions collide.
    for item in sorted([i for i in queue if i.get('manual_priority')], key=lambda i:i.get('override_at') or 0):
        queue.remove(item)
        queue.insert(min(len(queue),item['manual_priority']-1),item)
    for item in items: item['rescue_priority'] = None
    for n,item in enumerate(queue,1): item['rescue_priority']=n
    return sorted(items,key=lambda i:(i['rescue_priority'] is None,i['rescue_priority'] or 999,-i['last_signal_at']))
