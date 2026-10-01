"""Known test inputs are assigned, never chosen by the model."""
import pytest

from adversary.scenarios import SCENARIOS
from adversary.runtime.browser import BrowserAdapter
from adversary.models.action import ElementLocator, LocatorAlternative
from adversary.models.observation import BrowserElement, BrowserObservation
from adversary.inference.laya import LayaDecisionService


def adapter_for(scenario, label, tag='input', options=()):
    adapter=BrowserAdapter(None,'http://127.0.0.1:8011','s1',None)
    adapter.input_bindings=dict(scenario.fills)
    locator=ElementLocator(observation_id='o1',element_id='e1',
        alternatives=(LocatorAlternative(kind='css',value='#field'),))
    adapter.observation=BrowserObservation(id='o1',session_id='s1',step=0,url='http://127.0.0.1:8011',
        elements=(BrowserElement(locator=locator,accessible_name=label),))
    adapter.raw=[dict(tag=tag,type='text',disabled=False,options=options)]
    return adapter


@pytest.mark.parametrize('name',list(SCENARIOS))
def test_each_field_has_exactly_its_assigned_input(name):
    scenario=SCENARIOS[name]
    assert scenario.fills
    for label,value in scenario.fills:
        adapter=adapter_for(scenario,label)
        fills=[c for c in adapter.candidates(scenario.values) if c.action.type=='fill']
        assert len(fills)==1
        assert fills[0].action.value==value
    unknown=adapter_for(scenario,'Unspecified field')
    assert not any(c.action.type=='fill' for c in unknown.candidates(scenario.values))


def test_all_search_types_are_offered_but_text_payload_is_assigned():
    scenario=SCENARIOS['library-search']
    adapter=adapter_for(scenario,'Search by','select',[
        {'value':v,'label':v.title()} for v in ('artist','album','track')])
    selects=[c for c in adapter.candidates(scenario.values) if c.action.type=='select']
    assert [c.action.values for c in selects]==[('artist',),('album',),('track',)]
    assert [c.description for c in selects]==[
        'Select Artist in Search by', 'Select Album in Search by', 'Select Track in Search by']
    assert scenario.values==('QA Artist',)


def test_all_playlists_preserve_observed_option_ids():
    scenario=SCENARIOS['social-sharing']
    adapter=adapter_for(scenario,'Choose a playlist','select',[
        {'value':'opaque-id','label':'QA Playlist'}, {'value':'other-id','label':'Other'}])
    selects=[c for c in adapter.candidates(scenario.values) if c.action.type=='select']
    assert [c.action.values for c in selects]==[('opaque-id',),('other-id',)]


def test_assigned_fill_bypasses_model_after_operation_selection():
    scenario=SCENARIOS['library-search']
    adapter=adapter_for(scenario,'Search text')
    choices={c.id:c.description for c in adapter.candidates(scenario.values) if c.action.type=='fill'}
    class ForbiddenBackend:
        def predict(self,*args):raise AssertionError('No inference for assigned input')
    service=LayaDecisionService(backend=ForbiddenBackend(),max_calls=0)
    try:
        stages=[]
        assert service._predict({},choices,stages)==next(iter(choices))
        assert service.calls==0
        assert stages[0]['selection']=='deterministic'
        assert 'answer_confidence' not in stages[0]
    finally:
        service.executor.shutdown()


def test_duplicate_variants_are_separate_cases():
    assert dict(SCENARIOS['playlist-duplicate'].fills)['New playlist']=='QA Playlist'
    assert dict(SCENARIOS['playlist-duplicate-trimmed'].fills)['New playlist']=='  QA Playlist  '
