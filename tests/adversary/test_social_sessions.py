import asyncio
import os
import pytest
from adversary.runtime.social_sessions import coordinate_social


@pytest.mark.skipif(os.getenv('RWX_FRAMEWORK_TESTS') != '1', reason='Opt-in Chrome + disposable PostgreSQL')
def test_shared_fixture_social_protocol(tmp_path):
    result=asyncio.run(coordinate_social(tmp_path/'social'))
    assert result['status']=='passed',result
    assert result['checks']==7
    assert result['model_calls']==0
    for role in ('owner','follower','guest'):
        assert (tmp_path/'social'/f'{role}-trace.zip').is_file()
