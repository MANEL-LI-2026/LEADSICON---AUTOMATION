"""Provider-independent validation of speech and scene segments."""
import math


def validated_transcript(body):
    if not isinstance(body, dict):
        raise ValueError('Revisa la transcripción.')
    channels = []
    for channel in ('speech', 'scenes'):
        segments = body.get(channel, [])
        if not isinstance(segments, list) or len(segments) > 200:
            raise ValueError('Máximo 200 segmentos por capa.')
        clean = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError('Revisa los segmentos.')
            start, end = segment.get('start'), segment.get('end')
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start):
                raise ValueError('Los tiempos deben ser segundos válidos: inicio ≥ 0 y fin > inicio.')
            field = 'text' if channel == 'speech' else 'description'
            text = segment.get(field)
            if not isinstance(text, str) or not text.strip() or len(text) > 6000:
                raise ValueError('Cada segmento necesita texto (máximo 6000 caracteres).')
            item = {'start': start, 'end': end, field: text.strip()}
            if channel == 'speech':
                speaker = segment.get('speaker', 'Sin identificar')
                role = segment.get('role', 'unknown')
                if not isinstance(speaker, str) or not speaker.strip() or len(speaker) > 80 or role not in ('on_camera', 'voiceover', 'unknown'):
                    raise ValueError('Revisa el hablante y el tipo de voz.')
                item.update(speaker=speaker.strip(), role=role)
            clean.append(item)
        channels.append(sorted(clean, key=lambda segment: segment['start']))
    if type(body.get('reviewed', False)) is not bool:
        raise ValueError('El estado revisado debe ser verdadero o falso.')
    return *channels, body.get('reviewed', False)

