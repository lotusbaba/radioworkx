"""Hosted Jev choice client; credentials never enter reports or browser code."""
import math
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values

ENDPOINT = 'https://jev-ai.pro/api/v1/systemone'
INSTRUCTIONS = 'Choose the next action to achieve the testing goal, using current state and completed actions.'


class JevError(RuntimeError):
    pass


def credentials(env_file='.env'):
    values = dotenv_values(Path(env_file), interpolate=False) if Path(env_file).is_file() else {}
    key = (os.environ.get('JEV_AI_API_KEY') or os.environ.get('JEV_API_KEY')
           or values.get('JEV_AI_API_KEY') or values.get('JEV_API_KEY'))
    if not key:
        raise JevError('Set JEV_AI_API_KEY in the environment or ignored .env')
    return key


def probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid probability')
    return value


class JevClient:
    def __init__(self, key, model='jev-latest', transport=None):
        self._key = key
        self.model = model
        self.transport = transport

    def predict(self, state, choices):
        if not 2 <= len(choices) <= 255:
            raise JevError('Jev choice requests require 2–255 candidates')
        payload = {'model': self.model, 'state': state, 'questions': {'action': {
            'type': 'choice', 'instructions': INSTRUCTIONS, 'criteria': choices}}}
        try:
            # No redirects, proxy environment, provider fallback or automatic retries.
            with httpx.Client(timeout=90, trust_env=False, follow_redirects=False,
                              transport=self.transport) as client:
                response = client.post(ENDPOINT, json=payload, headers={'Authorization': 'Bearer ' + self._key})
        except httpx.HTTPError:
            raise JevError('Jev transport failed; request was not retried') from None
        if response.status_code != 200:
            raise JevError(f'Jev request failed (HTTP {response.status_code}); request was not retried')
        try:
            data = response.json()
            answer = data['answers']['action']
            selected = answer['choice']
            probs = answer['probabilities']
            if answer['type'] != 'choice' or selected not in choices or set(probs) != set(choices):
                raise ValueError('Invalid choice')
            probs = {k: probability(v) for k, v in probs.items()}
            if not math.isclose(sum(probs.values()), 1, abs_tol=0.001):
                raise ValueError('Invalid distribution')
            confidence = probability(answer['confidence'])
            if not isinstance(data['model'], str):
                raise ValueError('Invalid model')
            usage = {k: v for k, v in data.get('usage', {}).items()
                     if k in ('input_tokens', 'output_tokens') and type(v) is int and v >= 0}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise JevError('Jev returned an invalid choice response') from None
        return {'selected': selected, 'probabilities': probs, 'selected_probability': probs[selected],
                'provider_confidence': confidence, 'model': data['model'], 'usage': usage}
