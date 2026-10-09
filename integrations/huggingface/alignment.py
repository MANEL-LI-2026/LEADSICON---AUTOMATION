"""Pure timestamp alignment shared by the HF handler and offline tests."""
import math


def finite_time(value):
    return type(value) in (int, float) and math.isfinite(value)


def align_words(chunks, turns, duration):
    labels = {}
    speech = []
    for word in chunks:
        start, end = word.get('timestamp', (None, None))
        text = word.get('text', '').strip()
        if not text or not finite_time(start) or not finite_time(end) or not (0 <= start < min(end, duration) and end <= duration + .1):
            raise ValueError('Whisper returned a word without usable timestamps.')
        overlaps = {}
        for turn in turns:
            overlap = max(0, min(end, turn['end']) - max(start, turn['start']))
            if overlap:
                overlaps[turn['speaker']] = overlaps.get(turn['speaker'], 0) + overlap
        ranked = sorted(overlaps, key=overlaps.get, reverse=True)
        if len(ranked) > 1 and overlaps[ranked[1]] >= .8 * overlaps[ranked[0]]:
            speaker = 'Voces superpuestas'
        elif ranked:
            label = ranked[0]
            if label not in labels:
                labels[label] = 'Persona ' + str(len(labels) + 1)
            speaker = labels[label]
        else:
            speaker = 'Sin identificar'
        # Audio diarization identifies voices, never whether someone is on camera.
        if speech and speech[-1]['speaker'] == speaker and start - speech[-1]['end'] < 1.2 and len(speech[-1]['text']) < 500:
            speech[-1]['text'] += ' ' + text
            speech[-1]['end'] = min(duration, end)
        else:
            speech.append({'start': start, 'end': min(duration, end), 'speaker': speaker, 'role': 'unknown', 'text': text})
    if len(speech) > 200:
        raise ValueError('Too many speech segments.')
    return speech


def scene_windows(cuts, duration, maximum=24, interval=8):
    valid = sorted({0., duration, *(value for value in cuts if finite_time(value) and 0 < value < duration)})
    boundaries = [0.]
    for start, end in zip(valid, valid[1:]):
        # Also sample long takes, so their descriptions cover changes within a shot.
        count = max(1, math.ceil((end - start) / interval))
        boundaries.extend(start + (end - start) * index / count for index in range(1, count + 1))
    if len(boundaries) - 1 > maximum:
        indices = [round(index * (len(boundaries) - 1) / maximum) for index in range(maximum + 1)]
        boundaries = [boundaries[index] for index in sorted(set(indices))]
    return [{'start': round(start, 3), 'end': round(end, 3)} for start, end in zip(boundaries, boundaries[1:]) if end > start]
