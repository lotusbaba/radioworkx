"""Jev in the same bounded decision hierarchy used for the local Laya comparison."""
from .jev import JevClient
from .laya import LayaDecisionService


class JevBackend:
    device = 'hosted'

    def __init__(self, client):
        self.client = client
        self.last = None

    def predict(self, state, choices):
        self.last = self.client.predict(state, choices)
        return self.last['selected'], self.last['selected_probability'], self.last['probabilities']


class JevDecisionService(LayaDecisionService):
    strategy = 'custom-jev'

    def __init__(self, key, model='jev-latest', max_calls=18, transport=None):
        super().__init__(max_calls=max_calls, backend=JevBackend(JevClient(key, model, transport)))
        self.model = model

    def _predict(self, state, choices, stages):
        selected = super()._predict(state, choices, stages)
        if stages[-1]['selection'] == 'model':
            stages[-1].update({k: self.backend.last[k] for k in ('provider_confidence', 'model', 'usage')})
            stages[-1]['state'] = state
        return selected
